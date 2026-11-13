"""A basic app using the shared Hosts environment and its logging settings."""
from gppu import App, Env


class Basic(App):
    def main(self):
        self.Info('started on', Env.host, Env.os.value, 'as', Env.user)
        self.Debug('debug logging from the Hosts environment')


if __name__ == '__main__':
    Basic(environment='RAN/Hosts/_config/config.yaml').main()
