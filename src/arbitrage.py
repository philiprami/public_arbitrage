import os
import sys
import time
import json
import pytz
import smtplib
import argparse
import requests
import datetime
import itertools
import editdistance
import numpy as np
import pandas as pd

from utils import get_logger
from collections import defaultdict
from selenium.common import exceptions
from email.message import EmailMessage

from site_A import SiteA
from bovada import Bovada
from betvictor import BetVictor


### UTILS #####################################################################

def get_arbitrage(odds_A, odds_B):
    ''' check for presence of arbitrage between odds '''

    arbitrage = False
    higher = max(odds_A, odds_B)
    lower = min(odds_A, odds_B)

    if higher < 0 and lower < 0:
        return arbitrage
    elif higher >= 100 and lower >= 100:
        difference = higher - lower
        if difference >= 5:
            arbitrage = True
    else:
        difference = higher + lower
        if difference >= 5:
            arbitrage = True
            if difference >= 50:
                arbitrage = False

    return arbitrage

def check_lines(line_A, line_B):
    '''
    check for valid over/under lines
    line A for over, line B for under
    '''

    line_A = float(line_A)
    line_B = float(line_B)

    if line_A == line_B:
        return True
    elif line_A > line_B:
        return False
    else:
        return True

def calculate_pegged(odds_A, odds_B, peg=100):
    underdog_odds = max(odds_A, odds_B)
    favorite_odds = list(filter(lambda x: x != underdog_odds, [odds_A, odds_B]))[0]
    underdog_risk = peg
    underdog_payout = underdog_odds * 0.01 * underdog_risk

    results = None
    arbitrage_distance = 1000
    for favorite_risk in np.arange(underdog_risk, underdog_risk+100, 0.25):
        if favorite_odds >= 100:
            favorite_payout = favorite_odds * 0.01 * favorite_risk
        else:
            favorite_payout = abs(100 / float(favorite_odds)) * favorite_risk

        profit = underdog_payout - favorite_risk
        profit_2 = favorite_payout - underdog_risk
        if profit >= 0 and profit_2 >= 0:
            if abs(profit - profit_2) < arbitrage_distance:
                results = defaultdict(dict)
                results[str(underdog_odds)]['risk'] = round(underdog_risk, 2)
                results[str(underdog_odds)]['payout'] = round(underdog_payout, 2)
                results[str(favorite_odds)]['risk'] = round(favorite_risk, 2)
                results[str(favorite_odds)]['payout'] = round(favorite_payout, 2)
                arbitrage_distance = abs(profit - profit_2)

    return results

def calculate_wagers(**kwargs):
    if pd.isnull(kwargs['under_limit']) and pd.isnull(kwargs['over_limit']):
        results = calculate_pegged(kwargs['over'], kwargs['under'], peg=kwargs['peg'])
    else:
        for i in np.arange(0, kwargs['peg'], 2.5):
            peg = 100 - i
            results = calculate_pegged(kwargs['over'], kwargs['under'], peg=peg)
            if kwargs['over_limit']:
                over_amount = results[str(kwargs['over'])][kwargs['over_limit'][0]]
                if over_amount > kwargs['over_limit'][1]:
                    continue

            if kwargs['under_limit']:
                under_amount = results[str(kwargs['under'])][kwargs['under_limit'][0]]
                if under_amount > kwargs['under_limit'][1]:
                    continue

            break

    return results

###############################################################################


class Arbitrage(object):
    def __init__(self, league, *sites):
        self.name = 'arbitrage'
        self.league = league
        self.executed_bets = []
        self.get_start_times()
        self.logger = get_logger(self.league, self.name)
        with open('../data/player.json','r') as players_names:
            self.players = json.load(players_names)[self.league]

        self.site_map = {}
        for site_name in sites:
            self.site_map[site_name] = CORRESPONDING_SITE

        try:
            self.get_email_server()
        except:
            pass

    def get_start_times(self):
        '''
        IN: datetime format date
        OUT: matchups with timestamp

        EX:
            get_times('20191029')
            -> [['MIA-ATL', Timestamp('2019-10-29 23:30:00+0000', tz='UTC')]
        '''

        date = datetime.date.today().isoformat().replace('-', '')
        api_link = API_LINK
        response = requests.get(api_link)
        games_json = response.json()
        games = games_json['games']
        start_times = {}
        for game in games:
            start_datetime = pd.to_datetime(game[u'startTimeUTC'])
            matchup = '{}-{}'.format(game['vTeam']['triCode'], game['hTeam']['triCode'])
            start_times[matchup] = start_datetime

        self.start_times = start_times

    def get_email_server(self):
        ''' spin up email server '''

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.ehlo()
        server.starttls()
        server.login(os.getenv('GMAIL_USERNAME'), os.getenv('GMAIL_PASSWORD'))
        self.server = server

    def email(self, body):
        '''
        email arbitrage success
            if fails ... make new server ... try again
        '''

        os.system('say "arbitrage found"')
        msg = EmailMessage()
        address = os.getenv('GMAIL_USERNAME')
        msg['From'] = address
        msg['To'] = address
        msg['Subject'] = 'Arbitrage - {}'.format(self.league)
        msg.set_content(body)
        try:
            self.server.sendmail(address, address, msg.as_string())
        except:
            if hasattr(self, 'server'):
                del self.server
                self.get_email_server()
                self.email(body)
            else:
                self.logger.exception('message')
                self.logger.info(body)
                print(body)
                print('\n')

    def log_prop(self, prop_type, player, line, **kwargs):
        ''' log two way props '''

        body = 'Comp: {} - {} - {}\n'.format(prop_type, player, line)
        for key in kwargs:
            body += '{}: {}\n'.format(key, kwargs[key])

        self.logger.info(body.strip())

    def match_player(self, player_A, players_B, site_B):
        '''
        Use different strategies to match player_A with a
        player in players_B. If no match .. return None
        '''

        player_B = ''

        # case 1: same name
        if player_A in players_B:
            return player_A

        # case 2: check players.json file
        elif player_A in self.players:
            player_matches = self.players[player_A]
            if site_B in player_matches:
                comp_players = player_matches[site_B]
                comp_players = comp_players if type(player_matches[site_B]) == list else [comp_players]
                for player_match in comp_players:
                    if player_match in players_B:
                        return player_match

        # case 3: siteA player Ex: S.Curry
        elif len(player_A.split(' ')) == 2:
            first_name, last_name = player_A.split(' ')
            player_B = first_name[0] + '.' + last_name
            if player_B in players_B:
                return player_B

        # case 4: use edit distance
        for player_name in (player_A, player_B):
            for player_name_B in players_B:
                if editdistance.eval(player_name, player_name_B) <= 1:
                    return player_name_B

        return None

    def compare(self, combination):
        # if siteA in combo, make sure it is site b ... for player match
        combination = sorted(combination)
        site_A = list(filter(lambda x: x != 'siteA', combination))[0]
        site_B = list(filter(lambda x: x != site_A, combination))[0]

        ### keep record of players for logging
        players_list_A = set()
        players_list_B = set()
        matched_players_A = set()
        matched_players_B = set()
        ####################################

        prop_types_A = set(self.site_map[site_A].bets.keys())
        prop_types_B = set(self.site_map[site_B].bets.keys())
        prop_types = prop_types_A.intersection(prop_types_B)
        if not len(prop_types):
            self.logger.info('no prop types to compare')
            return

        for prop_type in prop_types:
            self.logger.info('comparing prop type {}'.format(prop_type))
            site_A_bets = self.site_map[site_A].bets[prop_type]
            site_B_bets = self.site_map[site_B].bets[prop_type]
            players_list_A = players_list_A.union(site_A_bets.keys())
            players_list_B = players_list_B.union(site_B_bets.keys())
            for player_A in site_A_bets:
                player_B = self.match_player(player_A, site_B_bets.keys(), site_B)
                if not player_B:
                    continue

                player_dict_A = site_A_bets[player_A]
                player_dict_B = site_B_bets[player_B]

                matchup_A = player_dict_A['matchup']
                matchup_B = player_dict_B['matchup']

                if matchup_A != matchup_B:
                    self.logger.info('{}({}) - {}({}) - team matchup does not match. skipping'.\
                      format(player_A, matchup_A, player_B, matchup_B))
                    continue

                # check matchup times
                if matchup_A not in self.start_times or matchup_B not in self.start_times:
                    continue

                now = pd.Timestamp.utcnow()
                if now > (self.start_times[matchup_A] - datetime.timedelta(minutes=5)):
                    self.logger.info('{} - gametime start within 5 minutes or started already. Removing from rotation.'.format(matchup_A))
                    # remove expired link from linked websites: bovada, betfair, betvictor
                    for site_name in self.site_map:
                        if hasattr(self.site_map[site_name], 'links'):
                            if matchup_A in self.site_map[site_name].links:
                                del self.site_map[site_name].links[matchup_A]
                    continue

                matched_players_A.add(player_A)
                matched_players_B.add(player_B)

                # extract odds to compare
                over_A = int(player_dict_A['over'])
                under_A = int(player_dict_A['under'])
                over_B = int(player_dict_B['over'])
                under_B = int(player_dict_B['under'])
                line_A = player_dict_A['line']
                line_B = player_dict_B['line']

                # log all props
                self.log_prop(prop_type, player_A, {site_A + ' over' : over_A, site_B + ' under' : under_B})
                self.log_prop(prop_type, player_A, {site_A + ' under' : under_A, site_B + ' over': over_B})

                # MAIN
                odds_matches = [(site_A, site_B, line_A, line_B, over_A, under_B),
                                (site_B, site_A, line_B, line_A, over_B, under_A)]

                for site_0, site_1, line_0, line_1, over, under in odds_matches:
                    if check_lines(line_0, line_1):
                        if get_arbitrage(over, under):
                            bet_key = '{}-{}-{}-{}-{}-{}'.\
                              format(site_0, site_1, prop_type, player_A, over, under)
                            if bet_key in self.executed_bets:
                                continue

                            kwargs = {'over' : over,
                                      'under' : under,
                                      'peg' : 100,
                                      'over_limit': None,
                                      'under_limit': None}

                            if 'bet_limit' in self.site_map[site_0].metadata:
                                kwargs['over_limit'] = \
                                  (self.site_map[site_0].metadata['limit_type'], self.site_map[site_0].metadata['bet_limit'])

                            if 'bet_limit' in self.site_map[site_1].metadata:
                                kwargs['under_limit'] = \
                                  (self.site_map[site_1].metadata['limit_type'], self.site_map[site_1].metadata['bet_limit'])

                            wager_dict = calculate_wagers(**kwargs)

                            # log and email arbitrage
                            self.logger.info('ARBITRAGE IDENTIFIED!')
                            wager_A = wager_dict[str(over)]
                            wager_B = wager_dict[str(under)]
                            str_over = '+' + str(over) if over > 0 else str(over)
                            str_under = '+' + str(under) if under > 0 else str(under)
                            heading = '{}({})-{}'.format(player_A, matchup_A, prop_type.upper())
                            body_over = '{} over {}:\n{} - {}'.format(site_0, line_0, str_over, wager_A)
                            body_under = '{} under {}:\n{} - {}'.format(site_1, line_1, str_under, wager_B)
                            self.email(heading + '\n' + body_over + '\n' + body_under)
                            self.executed_bets.append(bet_key)

        # log unmatched players
        unmatched_players_A = players_list_A - matched_players_A
        unmatched_players_B = players_list_B - matched_players_B
        self.logger.info('following players unmatched from {} - {}'.format(site_A, ', '.join(unmatched_players_A)))
        self.logger.info('following players unmatched from {} - {}'.format(site_B, ', '.join(unmatched_players_B)))

    def arbitrage(self):
        sites = [x for x, y in self.site_map.items() if y]
        combos = list(itertools.combinations(sites, 2))
        bets_parsed = []
        for combination in combos:
            for site_name in combination:
                if site_name not in bets_parsed:
                    try:
                        self.site_map[site_name].main()
                        bets_parsed.append(site_name)
                    except:
                        self.logger.info(site_name + ' parse unsuccesful')
                        self.logger.exception('message')
                        continue

            try:
                self.logger.info('comparing {} - {}'.format(combination[0], combination[1]))
                self.compare(combination)
            except:
                self.logger.info(' - '.join(combination) + ' comparison unsuccesful')
                self.logger.exception('message')

        # iterate through sites, log missing prop types
        for site_name in self.site_map:
            other_props = set()
            other_sites = filter(lambda x: x != site_name, self.site_map.keys())
            for site_name_2 in other_sites:
                other_props = other_props.union(self.site_map[site_name_2].prop_types)

            unmatched_props = other_props - self.site_map[site_name].prop_types
            self.logger.info('following prop types unmatched from {} - {}'.format(site_name, ', '.join(unmatched_props)))

    def main(self):
        self.logger.info('starting arbitrage round')

        now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        end_time = max([y for x, y in self.start_times.items()])
        if now > end_time:
            sys.exit('Times up')

        self.arbitrage()
        refresh_rate = 5 * 60 # runs every five minutes (max)
        wait_time = np.random.choice(range(60, refresh_rate))
        self.logger.info('waiting {} seconds'.format(wait_time))
        time.sleep(wait_time)
        self.main()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-league', choices=['mlb', 'nfl', 'nba'])
    parser.add_argument('-sites', nargs='+')
    args = parser.parse_args()

    arb = Arbitrage(args.league, *args.sites)
    arb.main()
