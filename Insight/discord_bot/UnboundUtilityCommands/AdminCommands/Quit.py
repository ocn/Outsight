from ..UnboundCommandBase import *
import os
import signal


class Quit(UnboundCommandBase):
    def __init__(self, unbound_service):
        super().__init__(unbound_service)
        self.cLock = asyncio.Lock(loop=self.client.loop)

    def command_description(self):
        return "!quit - Close and shut down the Insight application service."

    async def run_command(self, d_message: discord.Message, m_text: str = ""):
        async with self.cLock:
            options = dOpt.mapper_return_yes_no(self.client, d_message)
            options.set_main_header("Are you sure you want to shut down Insight? This will close the Insight "
                                    "server application. Note: You may get a 'CancelledError' message in Discord which "
                                    "you can safely ignore.")
            resp = await options()
            if resp:
                os.kill(os.getpid(), signal.SIGINT)
