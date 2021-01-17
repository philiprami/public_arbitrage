import os
import re
import sys
import json
import requests
import datetime
import numpy as np
import pandas as pd
from collections import defaultdict
from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.firefox.options import Options
from seleniumrequests import Firefox
from selenium.webdriver.support.ui import WebDriverWait
from utils import is_stale, sleep, convert_odds
from utils import get_logger, find_xpath_element, find_css_element


class SiteC(object):
    def __init__(self, league):
        self.name = 'siteC'
        self.sport = league
        self.bets = defaultdict(dict)
        self.prop_types = set()
        self.logger = get_logger(self.sport, self.name)
        with open('../data/metadata.json','r') as metadata:
            self.metadata = json.load(metadata)[self.name][self.sport]
        with open('../data/teams.json','r') as team_names:
            self.teams = json.load(team_names)[self.name][self.sport]

    def get_driver(self):
        while True:
            try:
                self.driver = Firefox(webdriver.FirefoxProfile(os.getenv('GECKO_PROFILE_PATH')),
                  executable_path=os.getenv('GECKO_DRIVER_PATH'))
                break
            except exceptions.WebDriverException:
                sleep()
                continue
            except:
                break

        self.wait = WebDriverWait(self.driver, timeout=15, poll_frequency=1.5)

    def get_links(self):
        links = []
        home_url = '<homeURL>'.\
          format(self.metadata['sport_id'])
        response = requests.get(home_url)
        events = response.json()
        events = filter(lambda x: x['group'] == self.metadata['tab_title'], events)
        for game in events:
            matchup = '-'.join([self.teams[x] for x in game['description'].split(' @ ')])
            game_number = str(game['id'])
            href = '<jsonLink>'.\
              format(game_number) # market group 4717 is to get a direct link to props... subject to change
            links.append([matchup, href])

        self.links = dict(links)

    def parse_json(self, matchup, game_link):
        prop_types_dict = self.metadata['prop_types_json']
        re_pattern = '(' + ') -|('.join(prop_types_dict.values()) + ')'
        response = requests.get(game_link)
        data = response.json()
        for section in data:
            prop_text = section['headers'][0]
            match = re.search(re_pattern, prop_text)
            if match:
                match_pos = match.lastindex - 1
                prop_type = list(prop_types_dict.keys())[match_pos]
                bets = section['markets']
                for bet in bets:
                    under, over = bet['o']
                    line = under['shD']
                    under_odds = str(convert_odds(under['pr']))
                    over_odds = str(convert_odds(over['pr']))
                    player = bet['opponentDescription'].strip()
                    odds_dict = {'line' : line, 'over' : over_odds,
                                 'under' : under_odds, 'matchup' : matchup}
                    self.bets[prop_type][player] = odds_dict

    def login(self):
        if not hasattr(self, 'driver'):
            self.get_driver()

        current_url = self.driver.current_url
        if '<homeURL>' not in current_url.lower():
            self.driver.get('<homeURL>')
        else:
            self.driver.refresh()

        sleep(3, 5)
        try:
            cookies_bttn = self.driver.find_element_by_css_selector('button[class*="cookies-policy"]')
            cookies_bttn.click()
            sleep()
        except:
            pass

        try:
            id_button = self.driver.find_element_by_css_selector('a[id*="my-account"]')
            return
        except:
            pass

        login_bttn = find_css_element(self, 'a[class*="login_bar"]')
        login_bttn.click()
        sleep()

        username_input = find_css_element(self, 'input[id="login_username"]')
        username_input.send_keys(os.getenv('USERNAME'))
        sleep()

        password_input = find_css_element(self, 'input[id="login_password"]')
        password_input.send_keys(os.getenv('PASSWORD'))
        sleep()

        submit_bttn = find_css_element(self, 'button[id="login_button"]')
        submit_bttn.click()
        sleep(5, 8)

    def main(self):
        if not hasattr(self, 'links'):
            self.get_links()

        self.bets = defaultdict(dict)
        for matchup in self.links:
            game_link = self.links[matchup]
            try:
                self.parse_json(matchup, game_link)
                sleep()
            except:
                self.logger.info('unable to extract bets for: {}'.format(game_link))
                self.logger.exception('message')
                continue

if __name__ == '__main__':
    pass
