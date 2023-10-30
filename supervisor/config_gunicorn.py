# -*-coding:utf-8 -*-
import multiprocessing


preload_app = True
max_requests=1024
max_requests_jitter=50

workers = multiprocessing.cpu_count() * 2 + 1
# Each process turn-on thread
threads = multiprocessing.cpu_count() * 2