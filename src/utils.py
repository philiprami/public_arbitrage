import os
import time
import logging
import requests
import datetime
import numpy as np
import pandas as pd
from retrying import retry
from collections import defaultdict
from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.common.keys import Keys

network_script = "var performance = window.performance || window.mozPerformance || window.msPerformance || window.webkitPerformance || {}; var network = performance.getEntries() || {}; return network;";

def sleep(x=1, y=3.5, step=0.5):
    secs = np.random.choice(np.arange(x, y, step))
    time.sleep(secs)

def is_stale(element, mult=False):
    try:
        if mult:
            mult[0].tag_name
        else:
            element.tag_name
    except exceptions.StaleElementReferenceException:
        return True
    except:
        pass

    return False

def find_css_element(object, css_selector):
    object.wait.until(lambda x: x.find_element_by_css_selector(css_selector))
    element = object.driver.find_element_by_css_selector(css_selector)
    if is_stale(element):
        object.driver.refresh()
        sleep()
        find_css_element(object, css_selector)

    return element

def find_xpath_element(object, xpath_selector):
    object.wait.until(lambda x: x.find_element_by_css_selector(xpath_selector))
    element = object.driver.find_element_by_css_selector(xpath_selector)
    if is_stale(element):
        object.driver.refresh()
        sleep()
        object.find_css_element(xpath_selector)

    return element

def get_logger(sport, name):
    today = datetime.date.today().isoformat()
    log_path = '../logs/{}/{}/{}/'.format(sport, name, today)
    try: os.mkdir(log_path)
    except: pass

    utc_time = '{:%H_%M_%S}'.format(datetime.datetime.now())
    logger_name = '{}.log'.format(utc_time)
    logger_file_name = log_path + logger_name

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)-12s - %(message)s \n',
                        datefmt='%m-%d %H:%M:%S',
                        filename=logger_file_name,
                        filemode='w')

    logger = logging.getLogger(name.upper().strip())
    return logger

def convert_odds(decimal_odds):
    if type(decimal_odds) in [str, bytes]:
        if '/' in decimal_odds:
            num, denom = decimal_odds.split('/')
            decimal_odds = (int(num) / float(denom)) + 1

    without_stake = decimal_odds - 1
    if without_stake > 1:
        american = without_stake * 100
    else:
        american = round(100/-without_stake)

    return int(american)

def retry_http_error(exception):
    """Return True if we hit a HTTP error, False otherwise"""
    return isinstance(exception, requests.exceptions.HTTPError)

@retry(retry_on_exception=retry_http_error, wait_exponential_multiplier=5000, stop_max_attempt_number=5)
def requests_call(url, **kwargs):
    r = requests.get(url, **kwargs)
    try:
        r.raise_for_status()
        return r
    except Exception as e:
        raise e

if __name__ == '__main__':
    pass
