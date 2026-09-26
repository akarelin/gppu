"""gppu.rest — provider: an AsyncApp's public methods over HTTP (mixin_Rest, from gppu/app.py).

One change: a method's arguments are described by ``gppu.params.schema``, the description the command line uses,
so ``POST /app/archive {"since": "3d", "db": "pg-trix"}`` resolves exactly as ``archive --since 3d --db pg-trix``.
"""
