import argparse


class InsightArgumentParser(object):
    @classmethod
    def get_cli_args(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", "-c",
                            help="Specifies a config file other than the default 'config.ini' to run the program with",
                            default="config.ini")
        parser.add_argument("--debug-km", "-k",
                            help="Start the application in debug mode to send kms starting at and above this id through all channel feeds.",
                            type=int)
        parser.add_argument("--force-ctime", "-f",
                            action="store_true",
                            help="If --debug_km is set, this flag will push kms to feeds with their time occurrence set to now.",
                            default=False)
        parser.add_argument("--debug-limit", "-l",
                            help="Sets the total limit of debug kms to push through feeds before exiting the program. Default is unlimited.",
                            type=int)
        parser.add_argument("--startup-debug", action="store_true",
                            help="Test startup and exit. This flag is mainly used for startup time testing.",
                            default=False)
        parser.add_argument("--schema-import", action="store_true",
                            help="Import the current Insight database schema to the database and exit.",
                            default=False)
        parser.add_argument("--skip-api-import", "-n", action="store_true",
                            help="Skip startup API static data import check.", default=False)
        parser.add_argument("--websocket", "-w", action="store_true",
                            help="Enable the experimental secondary ZK websocket connection.", default=False)
        parser.add_argument("--sde-db", "-s",
                            help="Specifies the name of the SDE database file relative to main.py. Download and extract the "
                                 "sqlite-latest.sqlite file from https://www.fuzzwork.co.uk/dump/",
                            type=str, default="sqlite-latest.sqlite")
        parser.add_argument("--auth", "-a", action="store_true",
                            help="Boot Insight in SSO token authorization code converter mode. Given an authorization "
                                 "token, Insight will provide a raw refresh_token. Mainly used for unit testing.",
                            default=False)
        parser.add_argument("--export-swagger-client", action="store_true",
                            help="Export the built ESI swagger client library to a zip archive in the Docker volume.",
                            default=False)
        return parser.parse_args()
