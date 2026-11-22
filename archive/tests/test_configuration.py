# .. archived 2026-11-22: what gppu's reduction removed from tests/test_configuration.py, as it was last


# .. from gppu/v3.7.9
def test_async_init_sees_its_configuration_after_the_environment_loads():
    from gppu import AsyncApp

    class Example(AsyncApp):
        def init(self):
            self.seen = (self.my('enabled'), glob('second/value'))
            return super().init()

    assert Example(environment='RAN').seen == (False, 2)
