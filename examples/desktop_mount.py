"""Mount the configured gppufs sources for desktop browsing, with no arguments."""
from pathlib import Path

from gppu import App, Env, Info
from gppu.desktop import mount
from gppu.fs import GppuFileSystem


class Desktop(App):
    def run(self):
        sources = {name: GppuFileSystem(location) for name, location in self.my('sources').items()}
        Info('Desktop', self.my('mount_point'))
        mount(sources, self.my('mount_point'))


if __name__ == '__main__':
    Env.from_env(name='desktop', app_path=Path(__file__).parent)
    Desktop().run()
