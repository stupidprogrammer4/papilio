app:
  modules:
    - "<<PKG>>.modules"
  features:
    - cqrs

run:
  entrypoint: "<<PKG>>.main:app"
  backend: uvicorn
  mode: dev
  host: 127.0.0.1
  port: 8000

fastapi:
  title: ""
  description: ""
  version: "0.0.0"

db:
  test_dsn: "postgresql+asyncpg://postgres:secure_pwd@0.0.0.0:5432/<<PKG>>_test_db"
  dsn: "postgresql+asyncpg://postgres:secure_pwd@0.0.0.0:5432/<<PKG>>_db"
  pool_timeout: 30
  pool_recycle: 1800
  pool_size: 20
  max_overflow: 5

crypto:
  encryption_key: "secret_key="
  password_salt: ""

redis:
  url: "redis://0.0.0.0:6379/0"
  max_connections: 10
  socket_timeout: 5.0
  socket_connect_timeout: 5.0
  health_check_interval: 30

rate_limit:
  enabled: true
  trusted_proxies: []
  general:
    limit: 120
    window_seconds: 60
  rules:
    login:
      limit: 5
      window_seconds: 300
    refresh:
      limit: 20
      window_seconds: 60

jwt:
  algorithm: "HS256"
  secret_key: ""
  access_token_expire_minutes: 60
  api_secret: ""

csrf:
  secret_key: "plSAxBp93Wc9LiuvD0TI_pMWUzf_mlK8SjPB3oROOhU"

storage:
  path: "media"
  temp_dir: "tmp"
  max_file_size: 5242880
  allowed_extensions: ["jpg", "jpeg", "png", "webp"]

es:
  hosts:
    - "http://0.0.0.0:9200"
  username: null
  password: null
  api_key: null
  verify_certs: false
  ca_certs: null

http:
  max_connections: 100
  max_keepalive_connections: 20
  keepalive_expiry: 30.0
  timeout: 15.0
  connect_timeout: 5.0
  follow_redirects: true

logging:
  level: "INFO"
  format: "console"      # "json" in production
  service: "<<PKG>>-api"
