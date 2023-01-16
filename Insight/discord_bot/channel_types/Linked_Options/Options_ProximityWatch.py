from . import Base_Feed
import discord
from functools import partial
from sqlalchemy.orm import Session
from typing import List
from sqlalchemy.exc import IntegrityError
import InsightExc
from . import opt_capradar
from InsightUtilities import LimitManager


class Options_ProximityIntel(opt_capradar):
    def yield_options(self):
        yield (self.InsightOptionRequired_addRegSys, True)
        yield (self.InsightOption_rmRegSys, False)
        yield (self.InsightOptionRequired_maxage, True)
        yield (self.InsightOption_sync, False)
        yield (self.InsightOption_minValue, False)
        yield from super(opt_capradar, self).yield_options()

    async def InsightOptionRequired_addRegSys(self, message_object: discord.Message):
        """Add a new system, constellation, or region watch - Add a new watch to display hostile activity occurring near you."""
        def make_options(search_str):
            options = discord_options.mapper_index(self.cfeed.discord_client, message_object)
            options.set_main_header(
                "Select a system, constellation, or region you wish to watch.")
            db: Session = self.cfeed.service.get_session()

            def header_make(row_list, header_text):
                if len(row_list) > 0:
                    options.add_header_row(header_text)
                    for i in row_list:
                        options.add_option(discord_options.option_returns_object(name=str(i), return_object=i))

            try:
                header_make(SearchHelper.search(db, tb_systems, tb_systems.name, search_str), "Systems")
                header_make(SearchHelper.search(db, tb_constellations, tb_constellations.name, search_str), "Constellations")
                header_make(SearchHelper.search(db, tb_regions, tb_regions.name, search_str), "Regions")
                options.add_header_row("Additional Options")
                options.add_option(discord_options.option_returns_object("Search again", return_object=None))
                return options
            except Exception as ex:
                raise ex
            finally:
                db.close()

        def add_list(row_ob, max_jump=None):
            db: Session = self.cfeed.service.get_session()
            try:
                if isinstance(row_ob, tb_systems):
                    row = tb_Filter_systems.get_row(self.cfeed.channel_id, row_ob.get_id(), self.cfeed.service)
                    row.max = max_jump
                    db.merge(row)
                elif isinstance(row_ob, tb_constellations):
                    db.merge(tb_Filter_constellations.get_row(self.cfeed.channel_id, row_ob.get_id(), self.cfeed.service))
                elif isinstance(row_ob, tb_regions):
                    db.merge(tb_Filter_regions.get_row(self.cfeed.channel_id, row_ob.get_id(), self.cfeed.service))
                db.commit()
            except Exception as ex:
                print(ex)
                raise InsightExc.Db.DatabaseError
            finally:
                db.close()

        search_opt = discord_options.mapper_return_noOptions(self.cfeed.discord_client, message_object)
        search_opt.set_main_header("Enter the name of a system, constellation, or region.\nHostile activity occurring "
                                   "within your selection will be posted to the proximity watch.\nNote: Additional "
                                   "watches can be added or removed after feed creation by running the "
                                   "‘!settings’ command.")
        search_opt.set_footer_text("Enter a name. Note: partial names are accepted: ")
        selected_option = None
        while selected_option is None:
            s_name = await search_opt()
            results = await self.cfeed.discord_client.loop.run_in_executor(None, partial(make_options, s_name))
            selected_option = await results()
        dist = None
        if isinstance(selected_option, tb_systems):
            gates = discord_options.mapper_return_noOptions_requiresInt(self.cfeed.discord_client, message_object)
            gates.set_main_header("Enter the number of jumps from this system to display activity. Hostile activity"
                                  " occurring within the set 'X' number of jumps away from your system will be "
                                  "displayed.\nEnter '0' to only track activity within the system itself.")
            gates.set_footer_text("Enter an integer:")
            dist = await gates()
        await self.cfeed.discord_client.loop.run_in_executor(None, partial(add_list, selected_option, dist))
        await self.reload(message_object)

    async def InsightOption_rmRegSys(self, message_object: discord.Message):
        """Remove a system, constellation, or region watch - Remove a previously added watch."""
        def make_options():
            db: Session = self.cfeed.service.get_session()
            remove_opt = discord_options.mapper_index_withAdditional(self.cfeed.discord_client, message_object)
            remove_opt.set_main_header("Select the item you wish to remove.")
            try:
                remove_opt.add_header_row("Watched systems for this feed")
                for i in db.query(tb_Filter_systems).filter(tb_Filter_systems.channel_id==self.cfeed.channel_id).all():
                    str_rep = "System: {}-----Gate jump proximity: {}".format(str(i), str(i.max))
                    remove_opt.add_option(discord_options.option_returns_object(name=str_rep, return_object=i))
                remove_opt.add_header_row("Watched constellations for this feed")
                for i in db.query(tb_Filter_constellations).filter(tb_Filter_constellations.channel_id==self.cfeed.channel_id).all():
                    str_rep = "Constellation: {}".format(str(i))
                    remove_opt.add_option(discord_options.option_returns_object(name=str_rep, return_object=i))
                remove_opt.add_header_row("Watched regions for this feed")
                for i in db.query(tb_Filter_regions).filter(tb_Filter_regions.channel_id==self.cfeed.channel_id).all():
                    str_rep = "Region: {}".format(str(i))
                    remove_opt.add_option(discord_options.option_returns_object(name=str_rep, return_object=i))
                return remove_opt
            except Exception as ex:
                print(ex)
                raise InsightExc.Db.DatabaseError
            finally:
                db.close()
        opt_row = await self.cfeed.discord_client.loop.run_in_executor(None, make_options)
        row = await opt_row()
        await self.delete_row(row)
        await self.reload(message_object)

    async def InsightOption_minValue(self, message_object: discord.Message):
        """Set minimum ISK value - Set the minimum ISK value for killmails."""

        def get_number(input_val: str):
            try:
                input_val = input_val.strip()
                num = "".join([c for c in input_val if c.isdigit() or c == '.'])
                n_modifier = "".join(a.casefold() for a in input_val if a.isalpha())
                num = float(num)
                if n_modifier.startswith('b'):
                    num = num * 1e+9
                elif n_modifier.startswith('m'):
                    num = num * 1e+6
                elif n_modifier.startswith('k'):
                    num = num * 1e+3
                else:
                    pass
                return num
            except:
                raise InsightExc.userInput.NotFloat

        def set_min_value(isk_val):
            db: Session = self.cfeed.service.get_session()
            try:
                row: tb_Filter_systems = db.query(tb_Filter_systems).filter(tb_Filter_systems.channel_id == self.cfeed.channel_id).one()
                row.minValue = isk_val
                db.merge(row)
                db.commit()
            except Exception as ex:
                print(ex)
                raise InsightExc.Db.DatabaseError
            finally:
                db.close()

        options = discord_options.mapper_return_noOptions(self.cfeed.discord_client, message_object)
        options.set_main_header("Set the minimum isk value for killmails. Mails below this value will not be posted. "
                                "Enter '0' for no limit.")
        options.set_footer_text("Enter a number. Examples: 500m, 10 billion, 500,000: ")
        resp = await options()
        val = get_number(resp)
        await self.cfeed.discord_client.loop.run_in_executor(None, partial(set_min_value, val))
        await self.reload(message_object)
        async with (await LimitManager.cm_hp(message_object.channel)):
            await message_object.channel.send("Minimum ISK value is now set at: {:,.2f} ISK.".format(val))


from discord_bot import discord_options
from database.db_tables import *
