"""The simplest app: load a mapping, read its own greeting, and log it."""
from gppu import App

ENVIRONMENT = {'basic': {'greeting': 'Hello'}}


class Basic(App):
    def main(self):
        self.Info(self.my('greeting'))


if __name__ == '__main__':
    Basic(environment=ENVIRONMENT).main()
