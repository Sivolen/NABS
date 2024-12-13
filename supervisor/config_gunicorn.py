# -*-coding:utf-8 -*-
import multiprocessing

bind = "0.0.0.0:8000"

# Increase the timeout if the operation takes a long time
timeout = 120

# Use the synchronous worker class if gevent is not needed
worker_class = 'sync'

# Number of worker processes
workers = multiprocessing.cpu_count() * 2 + 1

# Remove the threads parameter if gevent is used
# threads = multiprocessing.cpu_count() * 2

# Disable preloading the application
preload_app = True

# Disable max_requests and max_requests_jitter if they are not needed
max_requests = 1024
max_requests_jitter = 50

# Each process turn-on thread
# threads = multiprocessing.cpu_count() * 2
