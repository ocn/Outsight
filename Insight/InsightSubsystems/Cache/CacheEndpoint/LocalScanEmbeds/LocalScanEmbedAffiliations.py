from InsightSubsystems.Cache.CacheEndpoint.LocalScanEmbeds.LocalScanEmbedBase import LocalScanEmbedBase
from InsightUtilities.StaticHelpers import *
from InsightUtilities import EmbedLimitedHelper
from datetime import datetime


class LocalScanEmbedAffiliations(LocalScanEmbedBase):
    @classmethod
    def buffer_ship(cls):
        return 25

    @classmethod
    def _add_grouping(cls, e: EmbedLimitedHelper, scan: dict, grp: dict):
        total_proc = 0
        alive = Helpers.get_nested_value(grp, 0, "totalAlive")
        dead = Helpers.get_nested_value(grp, 0, "totalDead")
        name = Helpers.get_nested_value(grp, "", "name")[:75]
        strShipAvg = Helpers.get_nested_value(grp, 0, "strShipAvg")
        strShipMax = Helpers.get_nested_value(grp, 0, "strShipMax")
        ship_str_buffer = cls.get_buffer_len(avg_len=strShipAvg, max_len=strShipMax, buffer_max=cls.buffer_ship())
        header = "**{} -- Alive:{} Dead:{}**".format(name, alive, dead)
        e.field_buffer_start(name=header, name_continued="{} -- Continued".format(name), inline=False)
        e.field_buffer_start_bounds("```\n", "\n```")
        for ship_id_dict in Helpers.get_nested_value(grp, {}, "ships").values():
            shipId = Helpers.get_nested_value(ship_id_dict, 0, "shipID")
            ship_d = Helpers.get_nested_value(scan, {}, "ships", shipId, "ship")
            base_ship_value = Helpers.get_nested_value(ship_d, 0, "basePrice")
            is_super_titan = Helpers.get_nested_value(ship_d, False, "isSuperTitan")
            is_regular_cap = Helpers.get_nested_value(ship_d, False, "isCap")
            ship_name = Helpers.get_nested_value(ship_d, "", "type_name")
            ship_name_str = cls.get_alert_prefixed_ship(is_super_titan, is_regular_cap, base_ship_value) + ship_name
            alive = Helpers.get_nested_value(ship_id_dict, 0, "alive")
            lost = Helpers.get_nested_value(ship_id_dict, 0, "dead")
            lost_str = ":-{}".format(lost) if lost > 0 else ""
            al_str = "{}{}".format(alive, lost_str)
            avg_seconds = float(Helpers.get_nested_value(ship_id_dict, "", "avgSeconds"))
            avg_delay_str = "{}".format(MathHelper.str_min_seconds_convert(avg_seconds))
            field_line = "{:<{ship_len}} {:<5} {}".format(ship_name_str[:ship_str_buffer], al_str, avg_delay_str, ship_len=ship_str_buffer)
            if e.check_remaining_lower_limits(len(field_line) + 90, 1):
                return total_proc
            e.field_buffer_add(field_line)
            total_proc += alive + lost
        km_ratios = Helpers.get_nested_value(grp, {}, "kms").values()
        e.field_buffer_end_bounds()
        cls._add_summary_involved_mails(e, scan, km_ratios, max_to_post=3, ratio_threshold=.25)
        e.field_buffer_end()
        return total_proc

    @classmethod
    def _do_endpoint_logic_sync(cls, scan: dict, server_prefix: str) -> dict:
        e = EmbedLimitedHelper()
        e.set_color(cls.default_color())
        e.set_timestamp(datetime.utcnow())
        str_stats = cls.get_header_str(scan)
        totalQueried = Helpers.get_nested_value(scan, 0, "totalQueried")
        totalUnknownNames = Helpers.get_nested_value(scan, 0, "totalUnknownNames")
        totalKnown = Helpers.get_nested_value(scan, 0, "totalAlive") + Helpers.get_nested_value(scan, 0, "totalDead")
        allGroups = list(Helpers.get_nested_value(scan, {}, "alliances").values()) + list(Helpers.get_nested_value(scan, {}, "corporations").values())
        totalNonTruncPilots = 0
        totalNonTruncGroups = 0
        e.set_description("Affiliations are grouped by ship types. Time represents the average "
                          "last activity among all ship types for a group.\n\n{}".format(str_stats))
        e.set_author(name="Scan of {} pilots".format(totalQueried),
                     icon_url=URLHelper.type_image(1973, 64))
        e.set_footer(text="Run '{}s -h' for additional help and usages.".format(server_prefix))

        for grp in allGroups:
            total_pilot_notrunc = cls._add_grouping(e, scan, grp)
            if total_pilot_notrunc > 0:
                totalNonTruncPilots += total_pilot_notrunc
                totalNonTruncGroups += 1
            else:
                break  # too many chars break
        if totalQueried - totalNonTruncPilots - totalUnknownNames > 0:
            trunc_pilot = totalKnown - totalNonTruncPilots - totalUnknownNames
            trunc_group = len(allGroups) - totalNonTruncGroups
            e.field_buffer_start(name="TRUNCATED", name_continued="Truncated -- Continued", inline=False)
            e.field_buffer_start_bounds("```\n", "\n```")
            e.field_buffer_add("TRUNCATED PILOTS: {}\nTRUNCATED GROUPS: {}".format(
                trunc_pilot, trunc_group))
            if trunc_group >= 10:
                c_line = "Note: Use \"{}s -s\" to display pilot names linked to ships.".format(server_prefix)
                if e.check_line_fits(c_line):
                    e.field_buffer_add(c_line)
            e.field_buffer_end()
        return_result = {
            "embed": e.to_dict(),
        }
        return return_result

