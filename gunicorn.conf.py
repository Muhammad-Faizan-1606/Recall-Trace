"""Bounded WSGI runtime; migrations run once separately before deployment."""

import os

bind = f"0.0.0.0:{int(os.getenv('PORT', '8000'))}"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = 1
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
worker_tmp_dir = "/tmp"
accesslog = "-"
# Exclude query strings and request/response headers, which may contain credentials.
access_log_format = "%(h)s %(m)s %(U)s %(s)s %(D)s"
errorlog = "-"
capture_output = False
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
