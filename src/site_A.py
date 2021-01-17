import re
import os
import time
import json
import datetime
import numpy as np
import pandas as pd
from pprint import pformat
from collections import defaultdict
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.common import exceptions
from utils import is_stale, sleep, get_logger, find_css_element


class SiteA(object):
    def __init__(self, league):
        self.name = 'siteA'
        self.sport = league
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
                self.driver = webdriver.Firefox(webdriver.FirefoxProfile(os.getenv('GECKO_PROFILE_PATH')),
                  executable_path=os.getenv('GECKO_DRIVER_PATH'))
                break
            except exceptions.WebDriverException:
                sleep()
                continue
            except:
                break

        self.wait = WebDriverWait(self.driver, timeout=15, poll_frequency=1.5)

    def login(self):
        self.logger.info('logging in')

        username_css = 'input[class*="login-input"][name="username"]'
        password_css = 'input[class*="login-input"][name="password"]'
        submit_bttn_css = 'input[type="submit"]'

        username_input = self.find_css_element(username_css)
        password_input = self.find_css_element(password_css)
        submit_bttn = self.find_css_element(submit_bttn_css)

        username_input.send_keys(self.username)
        sleep()
        password_input.send_keys(self.password)
        sleep()
        submit_bttn.click()
        sleep()

    def get_bets(self):
        self.logger.info('getting betting page')

        current_url = self.driver.current_url
        home_url = '<homePageURL>'
        select_page = '<selectPageURL>'
        main_page = '<mainPageURL>'
        expired_page = '<expiredPageURL>'

        if current_url.lower() == home_url.lower():
            self.login()
            sleep()

        # from landing page
        elif home_url.lower() not in current_url.lower():
            self.driver.get(home_url)
            sleep()
            self.login()
            sleep()

        # from bets page, refresh, if expired, log in
        elif main_page.lower() in current_url.lower() or \
          main_page.lower() == current_url.lower():
            self.driver.refresh()
            sleep(0.25, 0.5)
            self.driver.switch_to_alert().accept()
            sleep()

            current_url = self.driver.current_url
            if expired_page.lower() in current_url.lower() or \
              expired_page.lower() == current_url.lower():
                self.driver.get(home_url)
                sleep()
                self.login()
                sleep()
            else:
                return

        # from session expired page
        elif expired_page.lower() == current_url.lower() or \
          expired_page.lower() in current_url.lower():
            self.driver.get(home_url)
            sleep()
            self.login()
            sleep()

        # otherwise navigate to select page
        elif current_url.lower() != select_page.lower():
            self.driver.get(select_page)
            sleep()

        # select specific sport bets
        mlb_css = self.metadata['select_css']
        continue_css = 'input[id="btnContinue"]'
        mlb_checkbox = self.find_css_element(mlb_css)
        continue_button = self.find_css_element(continue_css)
        mlb_checkbox.click()
        sleep()
        continue_button.click()
        sleep()

    def parse(self):
        self.logger.info('parsing props from bet page')
        self.bets = defaultdict(dict)

        _ = self.find_css_element(self.metadata['table_css'])
        soup = BeautifulSoup(self.driver.page_source, 'lxml')
        table = soup.select_one(self.metadata['prop_table_css'])
        rows = table.select('tr[class*="lines"]')
        top_rows = table.select('tr[class="linesRow"]')
        bot_rows = table.select('tr[class="linesRowBot"]')

        ### get header indices to reference matchups ##########################
        header_index_l = []
        for row in rows:
            if row.attrs['class'][0] == 'linesSubHeader':
                matchup_l = []
                for team in self.teams.keys():
                    if len(matchup_l) < 2:
                        if team in row.text:
                            pos = row.text.index(team)
                            matchup_l.append([pos, self.teams[team]])
                    else:
                        break

                matchup = '-'.join(x[1] for x in sorted(matchup_l, key=lambda x: x[0]))
                if matchup:
                    header_index_l.append([rows.index(row), matchup])

        #######################################################################

        prop_types_dict = self.metadata['prop_types']
        re_pattern = '.*?' + '|.*?'.join(prop_types_dict.values())
        for top_tag, bot_tag in zip(top_rows, bot_rows):
            top_tag_text = list(top_tag)[2].text.strip().replace(u'\xbd', u'.5')\
                .replace(u'\xa0', u' ')
            bot_tag_text = list(bot_tag)[2].text.strip().replace(u'\xbd', u'.5')\
                .replace(u'\xa0', u' ')

            match = re.match(re_pattern, top_tag_text)
            if match:
                match_pos = match.lastindex - 1
                prop_type = list(prop_types_dict.keys())[match_pos]
                if not match.groups():
                    continue

                if not np.any(match.groups()): #????? REMOVE
                    continue

                player = np.any(match.groups()).strip()
                top_row_id = top_tag.select_one('input').attrs['name']
                bot_row_id = bot_tag.select_one('input').attrs['name']
                odds_text = list(top_tag)[5].text.strip().replace(u'\xbd', u'.5')
                odds_text_2 = list(bot_tag)[5].text.strip().replace(u'\xbd', u'.5')
                odds_match = re.search('o?(\d+\.?\d?)?\s?(\-\d+|\+\d+)', odds_text)
                odds_match_2 = re.search('u?(\d+\.?\d?)?\s?(\-\d+|\+\d+)', odds_text_2)
                pos = rows.index(top_tag)
                matchup = [y for (x, y) in header_index_l if x < pos][-1]
                if odds_match and odds_match_2:
                    if len(odds_match.groups()) > 1:
                        line, odds = odds_match.groups()
                        line_2, odds_2 = odds_match_2.groups()
                    else:
                        odds = odds_match.groups()[0]
                        odds_2 = odds_match_2.groups()[0]
                        line = '0.5'

                    odds_dict = {'line' : line, 'over' : odds, 'under' : odds_2,
                                 'over_id' : top_row_id, 'under_id' : bot_row_id,
                                 'matchup' : matchup}

                    self.bets[prop_type][player] = odds_dict
                    self.prop_types.add(prop_type)
                    self.logger.info('{} - {} - {}'.format(prop_type, player, odds_dict))
            else:
                if top_tag_text not in self.non_matches:
                    self.logger.info('no match for wager - {}'.format(top_tag_text))
                    self.non_matches.add(top_tag_text)

    def main(self):
        self.get_bets()
        self.parse()

if __name__ == '__main__':
    pass
