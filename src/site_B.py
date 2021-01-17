import os
import re
import sys
import time
import json
import datetime
import numpy as np
import pandas as pd
from pprint import pformat
from collections import defaultdict
from bs4 import BeautifulSoup
from selenium import webdriver
from email.mime.multipart import MIMEMultipart
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common import exceptions
from seleniumrequests import Firefox
from utils import find_css_element, is_stale, sleep, get_logger, requests_call, find_css_element


class SiteB(object):
    def __init__(self, league):
        self.name = 'SiteB'
        self.sport = league
        self.bets = defaultdict(dict)
        self.username = os.getenv('USERNAME')
        self.password = os.getenv('PASSWORD')
        self.logger = get_logger(self.sport, self.name)
        self.non_matches = set()
        self.prop_types = set()
        with open('../data/metadata.json','r') as metadata:
            self.metadata = json.load(metadata)[self.name][self.sport]
        with open('../data/teams.json','r') as team_names:
            self.teams = json.load(team_names)[self.name][self.sport]
        while True:
            try:
                self.driver = Firefox(webdriver.FirefoxProfile(os.getenv('GECKO_PROFILE_PATH')),
                  executable_path=os.getenv('GECKO_DRIVER_PATH'))
                break
            except exceptions.WebDriverException:
                sleep()
            except Exception as e:
                print(e)
                break

        self.wait = WebDriverWait(self.driver, timeout=15, poll_frequency=1.5)

    def get_homepage(self):
        self.logger.info('fetching home page')
        home_url = self.metadata['home_url']
        current_url = self.driver.current_url

        if home_url.lower() not in current_url.lower():
            self.driver.get('https://' + home_url)

        sleep()

    def login(self):
        self.get_homepage()

        # check for profile element, if present -> already logged in
        profile_css = 'bx-header-logged-in-menu-ch'
        try:
            self.driver.find_element_by_css_selector(profile_css)
            return
        except exceptions.StaleElementReferenceException:
            self.driver.refresh()
            sleep()
            self.login()
        except exceptions.NoSuchElementException:
            pass

        self.logger.info('logging in')

        login_css = 'a[routerlink*="login"]'
        login_button = self.find_css_element(login_css)
        login_button.click()
        sleep()

        username_css = 'input[id="email"]'
        password_css = 'input[id="login-password"]'
        submit_bttn_css = 'button[id="login-submit"]'

        username_input = self.find_css_element(username_css)
        password_input = self.find_css_element(password_css)
        submit_bttn = self.find_css_element(submit_bttn_css)

        username_input.send_keys(self.username)
        sleep()
        password_input.send_keys(self.password)
        sleep()
        submit_bttn.click()
        sleep()

        # check for captcha
        captcha_css = 'button[id="login-submit"][disabled]'
        try:
            _ = self.find_css_element(captcha_css)
            raw_input('Press continue once captcha is filled.\n')
            self.logger.info('successful login')
        except:
            self.logger.info('unsuccessful login')
            pass

    def get_gamelinks(self):
        self.logger.info('acquiring game links')

        self.get_homepage()
        sleep(5, 8)

        none = self.find_css_element('div.grouped-events')
        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        next_events_table = soup.find('sp-next-events')
        # next_events_table.select('sp-coupon')
        for container in next_events_table.select('div.grouped-events'):
            description = container.select_one('h4[class*="league-header"]').text.strip()
            if self.metadata['tab_title'] in description:
                links = []
                links_soup = container.select('span[class*="game-view-cta"]')
                for l_soup in links_soup:
                    try:
                        link_soup = l_soup.select_one('a[class="game-count"]')
                        link = self.metadata['home_link'] + link_soup.attrs['href']
                        matchup_l = []
                        for team in self.teams.keys():
                            if len(matchup_l) < 2:
                                if team in link:
                                    pos = link.index(team)
                                    matchup_l.append([pos, self.teams[team]])
                            if len(matchup_l) == 2:
                                matchup = '-'.join(x[1] for x in sorted(matchup_l, key=lambda x: x[0]))
                                links.append((matchup, link))
                                break
                    except:
                        pass

                self.links = dict(links)
                if len(links):
                    self.logger.info('successful gathered game links')
                else:
                    self.logger.info('no game links found for today')

                return

    def get_gamelinks_v2(self):
        self.logger.info('acquiring game links')
        self.get_homepage()
        network = self.driver.execute_script("return window.performance.getEntries();")
        links = filter(lambda x : 'initiatorType' in x, network)
        links = filter(lambda x : x['initiatorType'] == 'xmlhttprequest', links)
        links = filter(lambda x : 'bovada.lv/services/' in x['name'] and 'preMatchOnly=true' in x['name'], links)
        links = list(links)
        if len(links):
            self.links = {}
            link = links[0]['name']
            res = requests_call(link)
            data = res.json()
            gamelinks = [x['link'] for x in data[0]['events']]
            for gamelink in gamelinks:
                matchup = '-'.join([self.teams[x] for x in re.findall('|'.join(self.teams.keys()), gamelink)])
                self.links[matchup] = JSON_LINK + gamelink
        else:
            self.logger.info('no game links found for today')

    def parse_v2(self, game_link):
        self.logger.info('parsing link - {}'.format(game_link))
        matchup_dict = {y : x for (x, y) in self.links.items()}
        matchup = matchup_dict[game_link]

        res = requests_call(game_link)
        data = res.json()
        events = data[0]['events'][0]['displayGroups']
        for group in events:
            if group['description'] == '<targetDescription>':
                target_group = group

        prop_types_dict = self.metadata['prop_types']
        re_pattern = '|'.join(prop_types_dict.values())
        for row in target_group['markets']:
            prop = row['description']
            match = re.search(re_pattern, prop)
            if match:
                match_pos = match.lastindex - 1
                player = np.any(match.groups()).strip()
                prop_type = list(prop_types_dict.keys())[match_pos]
                for outcome in row['outcomes']:
                    if outcome['description'] == 'Over':
                        over_odds = outcome['price']['american'].replace('EVEN', '+100')
                    else:
                        under_odds = outcome['price']['american'].replace('EVEN', '+100')

                if prop_type in ["DOUBLE", "TRIPLE"]:
                    line = '0.5'
                else:
                    line = row['outcomes'][0]['price']['handicap']

                odds_dict = {'line' : line, 'matchup' : matchup,
                             'over' : over_odds, 'under' : under_odds}

                self.bets[prop_type][player] = odds_dict
                self.prop_types.add(prop_type)
                self.logger.info('{} - {} - {}'.format(prop_type, player, odds_dict))
            else:
                if prop not in self.non_matches:
                    self.logger.info('no match for wager - {}'.format(prop))
                    self.non_matches.add(prop)

    def parse(self, game_link):
        self.logger.info('parsing link - {}'.format(game_link))

        self.driver.get(game_link)
        sleep(3, 5)

        matchup_dict = {y : x for (x, y) in self.links.items()}
        matchup = matchup_dict[game_link]

        css_selector = 'article[class*="coupon-container"]'
        none = self.find_css_element(css_selector)
        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        prop_types_dict = self.metadata['prop_types']
        re_pattern = '|'.join(prop_types_dict.values())

        rows = soup.select(css_selector)
        for row in rows:
            prop = row.find('h3').text.replace(u'\xa0', u' ').strip()
            match = re.search(re_pattern, prop)
            if match:
                match_pos = match.lastindex - 1
                player = np.any(match.groups()).strip()
                prop_type = list(prop_types_dict.keys())[match_pos]
                if prop_type in ["DOUBLE", "TRIPLE"]:
                    line = '0.5'
                else:
                    line_tag = row.select_one('ul[class="spread-header"]')
                    line = line_tag.text.strip().replace('.0', '')

                odds_tags = row.select('span[class="bet-price"]')
                odds = [x.text.strip().replace(u'\xbd', u'.5')\
                    .replace(u'EVEN', u'+100') for x in odds_tags]
                over_odds, under_odds = odds

                odds_dict = {'line' : line, 'matchup' : matchup,
                             'over' : over_odds, 'under' : under_odds}

                self.bets[prop_type][player] = odds_dict
                self.prop_types.add(prop_type)
                self.logger.info('{} - {} - {}'.format(prop_type, player, odds_dict))

            else:
                if prop not in self.non_matches:
                    self.logger.info('no match for wager - {}'.format(prop))
                    self.non_matches.add(prop)

    def main(self):
        if not hasattr(self, 'links'):
            self.get_gamelinks_v2()

        self.bets = defaultdict(dict)
        for game_link in self.links.values():
            try:
                self.parse_v2(game_link)
            except:
                self.logger.info('unable to extract bets for: {}'.format(game_link))
                self.logger.exception('message')

if __name__ == '__main__':
    pass
