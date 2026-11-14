"""A basic app using the shared RAN environment and its logging settings."""
from gppu import App, Env


class Basic(App):
    def main(self):
        self.Info('started on', Env.host, Env.os.value, 'as', Env.user)
        self.Debug('debug logging from the RAN environment')


if __name__ == '__main__':
    Basic(environment='RAN').main()
