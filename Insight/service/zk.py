import sys
import queue
import datetime
import service
from sqlalchemy.orm import Session
import database.db_tables as dbRow
from database.db_tables import tb_meta
import os
import statistics
import traceback
import aiohttp
import asyncio
import janus
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import InsightLogger
import time
from InsightSubsystems.Cache.CacheEndpoint import LastShip
from InsightUtilities.StaticHelpers import Helpers


class zk(object):
    def __init__(self, service_module):
        assert isinstance(service_module, service.ServiceModule)
        self.logger = InsightLogger.InsightLogger.get_logger('ZK', 'ZK.log')
        self.service = service_module
        self.config = self.service.config
        self.ws_url = self.config.get("ZK_WS_URL")
        self.redisq_base_url = self.config.get("ZK_REDISQ_URL")
        self.zk_stream_url = self.generate_redisq_url()
        self.run = True
        self.error_ids_404 = {}
        self.error_ids_non404 = {}
        self._km_preProcess: janus.Queue = None  # raw json, before insertion to database
        self._km_postProcess: janus.Queue = None  # fully finished sqlalchemy objects with names resolved
        self.delay_km = queue.Queue()  # delay from occurrence to load
        self.delay_process = queue.Queue()  # process/name resolve delay
        self.delay_next = queue.Queue()  # delay between zk requests
        self.run_websocket = self.service.cli_args.websocket

    @staticmethod
    def add_delay(q, other_time, minutes=False):
        try:
            assert isinstance(q, queue.Queue)
            div_s = 60 if minutes else 1
            q.put_nowait(((datetime.datetime.utcnow() - other_time).total_seconds()) / div_s)
        except Exception as ex:
            print(ex)

    @staticmethod
    def avg_delay(q, median=False):
        assert isinstance(q, queue.Queue)
        values = []
        total = 0
        avg = 0
        try:
            while True:
                values.append(q.get_nowait())
        except queue.Empty:
            try:
                total = len(values)
                if median:
                    avg = statistics.median(values)
                else:
                    avg = sum(values) / total
            except:
                pass
        except Exception as ex:
            print(ex)
        finally:
            return (total, round(avg, 1))

    def get_stats(self):
        _tmp_km_delay = self.avg_delay(self.delay_km, median=True)
        km_delay = (_tmp_km_delay[0], _tmp_km_delay[1] if _tmp_km_delay[1] <= 100 else 99)
        km_process = self.avg_delay(self.delay_process)
        km_next = self.avg_delay(self.delay_next)
        return (km_delay[0], km_delay[1], km_process[1], km_next[1])

    @staticmethod
    def generate_identifier():
        filename = 'zk_identifier.txt'
        try:
            with open(filename, 'r') as f:  # legacy check. Import the id to the database and then delete the file.
                text = f.read()
                if tb_meta.set("zk_identifier", {"value": text}):
                    print("Successfully imported the ZK identifier into the database. "
                          "It is safe to remove the legacy '{}' file".format(filename))
                else:
                    print("Error importing legacy identifier for ZK. Stopping...")
                    sys.exit(1)
            try:
                os.remove(filename)
            except Exception as ex:
                print(ex)
                print("Error removing legacy ZK identifier file. You can remove the file '{}' as it has been "
                      "imported to the database and no longer needed.".format(filename))
            return text
        except FileNotFoundError:
            d = tb_meta.get("zk_identifier")
            zk_id = Helpers.get_nested_value(d, "", "data", "value")
            if len(zk_id) <= 5:
                print("ZK id error - too short or not set")
                sys.exit(1)
            else:
                return zk_id

    def generate_redisq_url(self, no_identifier=False):
        if self.config.get("ZK_ID_RESET"):
            if not tb_meta.delete("zk_identifier"):
                print("Error resetting zk identifier")
                sys.exit(1)
            else:
                print("ZK identifier was reset.")
        identifier = self.generate_identifier()
        base_url = self.config.get("ZK_REDISQ_URL")
        if no_identifier or identifier is None:
            return base_url
        else:
            return "{}?queueID={}&ttw=10".format(base_url, identifier)

    def url_stream(self):
        return self.zk_stream_url

    def url_websocket(self):
        return self.ws_url

    def _make_km(self, km_json):
        """returns the cached km object if it does not exist, returns none if error or already exists"""
        result = None
        pull_start_time = datetime.datetime.utcnow()
        try:
            if dbRow.tb_kills.make_row(km_json, self.service) is not None:
                dbRow.name_resolver.api_mass_name_resolve(self.service, error_ids_404=self.error_ids_404,
                                                          error_ids_non404=self.error_ids_non404, exclude_nonentity=True)
                db: Session = self.service.get_session()
                try:
                    result = dbRow.tb_kills.get_row(km_json, self.service)
                    self.add_delay(self.delay_km, result.killmail_time, minutes=True)
                    result.loaded_time = datetime.datetime.utcnow()  # adjust for name resolve
                    self.add_delay(self.delay_process, pull_start_time)
                except Exception as ex:
                    print(ex)
                    traceback.print_exc()
                finally:
                    db.close()
        except Exception as ex:
            print("make_km error: {}".format(ex))
            traceback.print_exc()
        finally:
            return result

    def debug_simulate(self):
        if self.service.cli_args.debug_km:
            msg = "Starting debug mode.\nStarting KM ID: {}\nForce time to now: {}\nKM Limit: {}\n".format(
                str(self.service.cli_args.debug_km), str(self.service.cli_args.force_ctime),
                str(self.service.cli_args.debug_limit))
            print(msg)
            self.service.channel_manager.post_message(msg)
            db: Session = self.service.get_session()
            try:
                time.sleep(1)
                results = db.query(dbRow.tb_kills).filter(dbRow.tb_kills.kill_id >=self.service.cli_args.debug_km).limit(self.service.cli_args.debug_limit).all()
                db.close()
                for km in results:
                    if self.service.cli_args.force_ctime:
                        km.killmail_time = datetime.datetime.utcnow()
                    self._km_postProcess.sync_q.put_nowait(km)
            except Exception as ex:
                print(ex)
            finally:
                db.close()
            msg = "Debugging is now finished. Switching back to streaming live kms."
            print(msg)
            self.service.channel_manager.post_message(msg)

    async def pull_kms_redisq(self):
        """pulls kms using redisq"""
        lg = InsightLogger.InsightLogger.get_logger('ZK.redisq', 'ZK.log', child=True)
        async with aiohttp.ClientSession(headers=self.service.get_headers()) as client:
            msg = "Started zk stream (RedisQ/polling) coroutine."
            print(msg)
            lg.info(msg)
            next_delay = datetime.datetime.utcnow()
            while self.run:
                try:
                    async with client.get(url=self.url_stream(), timeout=45) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            package = data.get('package')
                            if package is not None:
                                await self._km_preProcess.async_q.put(package)
                            if not self.run_websocket:
                                self.add_delay(self.delay_next, next_delay)
                                next_delay = datetime.datetime.utcnow()
                        elif resp.status == 429:  # error limited
                            print("{} {}".format(str(datetime.datetime.utcnow()),
                                                 "zKill error limited. Are you using more than 1 bot with the same zk queue identifier? Delete your 'zk_identifier.txt' file."))
                            await asyncio.sleep(900)
                        else:
                            headers = resp.headers
                            body = await resp.text()
                            print("{} - RedisQ zk error code: {}".format(str(datetime.datetime.utcnow()), resp.status))
                            lg.warning('Error: {} Headers: {} Body: {}'.format(resp.status, str(headers), str(body)))
                            if 400 <= resp.status < 500:
                                await asyncio.sleep(300)
                            else:
                                await asyncio.sleep(120)
                except asyncio.TimeoutError:
                    await asyncio.sleep(15)
                    lg.info('Timeout.')
                except Exception as ex:
                    print('ZK RedisQ(polling) error: {}'.format(ex))
                    lg.exception(ex)
                    await asyncio.sleep(30)
                await asyncio.sleep(.1)

    def ws_extract(self, data):
        new_res = {}
        try:
            new_res['killID'] = data['killmail_id']
            new_res['killmail'] = data
            new_res['zkb'] = data['zkb']
        except Exception as ex:
            traceback.print_exc()
            print(ex)
            new_res = {}
        finally:
            return new_res

    async def pull_kms_ws(self):
        if self.run_websocket:
            lg = InsightLogger.InsightLogger.get_logger('ZK.ws', 'ZK.log', child=True)
            lg_msg = "Started zk stream (WebSocket) coroutine."
            lg.info(lg_msg)
            print(lg_msg)
            async with aiohttp.ClientSession(headers=self.service.get_headers()) as client:
                while self.run:
                    next_delay = datetime.datetime.utcnow()
                    try:
                        async with client.ws_connect(self.url_websocket(), heartbeat=10, receive_timeout=120) as ws:
                            lg.info('ZK WebSocket connection established.')
                            await ws.send_json(data={"action": "sub", "channel": "killstream"})
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    package = self.ws_extract(msg.json())
                                    if package:
                                        await self._km_preProcess.async_q.put(package)
                                        self.add_delay(self.delay_next, next_delay)
                                        next_delay = datetime.datetime.utcnow()
                                    else:
                                        lg.warning("ZK WebSocket package error.")
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    lg.warning("ZK WS error response.")
                                else:
                                    lg.warning("ZK WebSocket unknown response.")
                    except asyncio.TimeoutError:
                        lg.info("Websocket timeout. Restarting the websocket connection.")
                        await asyncio.sleep(15)
                    except Exception as ex:
                        lg_msg = 'ZK WebSocket error: {} - {}'.format(type(ex), str(ex))
                        print(lg_msg)
                        lg.warning(lg_msg)
                        lg.exception(ex)
                    await asyncio.sleep(40)

    async def coroutine_process_json(self, zk_thread_pool: ThreadPoolExecutor):
        lg = InsightLogger.InsightLogger.get_logger('ZK.json', 'ZK.log', child=True)
        msg = 'Started zk data processing coroutine.'
        print(msg)
        lg.info(msg)
        loop = asyncio.get_event_loop()
        while True:
            try:
                json_data = await self._km_preProcess.async_q.get()
                st = InsightLogger.InsightLogger.time_start()
                km = await loop.run_in_executor(zk_thread_pool, partial(self._make_km, json_data))
                if km is not None:
                    await self._km_postProcess.async_q.put(km)
                    InsightLogger.InsightLogger.time_log(lg, st, 'JSON parse km_id: {}'.format(km.kill_id), 3500)
            except Exception as ex:
                print(ex)

    async def coroutine_filters(self, zk_thread_pool: ThreadPoolExecutor):
        lg = InsightLogger.InsightLogger.get_logger('ZK.filters', 'ZK.log', child=True)
        LastShipEndpoint: LastShip = LastShip()
        msg = "Started zk filter coroutine."
        print(msg)
        lg.info(msg)
        loop = asyncio.get_event_loop()
        while True:
            try:
                km = await self._km_postProcess.async_q.get()
                st = InsightLogger.InsightLogger.time_start()
                await loop.run_in_executor(zk_thread_pool, partial(self.service.channel_manager.send_km, km))
                InsightLogger.InsightLogger.time_log(lg, st, 'Filer pass km_id: {}'.format(km.kill_id), 2500)
                LastShipEndpoint.reset_last_ships_background(km)
            except Exception as ex:
                print(ex)

    async def make_queues(self):
        self._km_preProcess = janus.Queue()
        self._km_postProcess = janus.Queue()
