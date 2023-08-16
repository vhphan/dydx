import itertools
import json
import time
from datetime import datetime, timedelta

import pandas as pd

from program.constants import RESOLUTION, EXPIRATION_OFFSET, FIND_COINTEGRATED, TEST_MODE
from program.constants import TEST_MODE_MARKET_LENGTH, MAX_HALF_LIFE
from program.decorate import on_error_abort
from program.func_cointegration import calculate_cointegration
from program.func_connections import connect_dydx
from program.func_utils import get_iso_timestamps, format_number


class TradingBot:

    def __init__(self) -> None:
        self.df_market_prices = None
        self.tradeable_markets = []
        self.criteria_met_pairs = []
        self.client = connect_dydx()

    def place_market_order(self, market, side, size, price, reduce_only):
        client = self.client
        # Get Position Id
        account_response = client.private.get_account()
        position_id = account_response.data["account"]["positionId"]

        server_time = client.public.get_time()
        expiration = datetime.fromisoformat(
            server_time.data["iso"].replace("Z", "")) + timedelta(seconds=EXPIRATION_OFFSET)

        placed_order = client.private.create_order(
            position_id=position_id,  # required for creating the order signature
            market=market,
            side=side,
            order_type="MARKET",
            post_only=False,
            size=size,
            price=price,
            limit_fee='0.015',
            expiration_epoch_seconds=expiration.timestamp(),
            time_in_force="FOK",
            reduce_only=reduce_only,
        )
        return placed_order.data

    @on_error_abort
    def abort_all_positions(self) -> list:
        client = self.client

        # Cancel all orders
        client.private.cancel_all_orders()

        # Protect API
        time.sleep(0.5)

        # Get markets for reference of tick size
        markets = client.public.get_markets().data

        # Protect API
        time.sleep(0.5)

        # Get all open positions
        positions = client.private.get_positions(status="OPEN")
        all_positions = positions.data["positions"]

        close_orders = []

        # If no open positions, return
        if len(all_positions) == 0:
            return close_orders

        # Handle open positions
        for position in all_positions:
            market = position["market"]
            side = "SELL" if position["side"] == "LONG" else "BUY"
            price = float(position["entryPrice"])

            accept_price = price * 1.7 if side == "BUY" else price * 0.3
            tick_size = markets["markets"][market]["tickSize"]
            accept_price = format_number(accept_price, tick_size)

            order = self.place_market_order(
                market,
                side,
                position["sumOpen"],
                accept_price,
                True
            )
            close_orders.append(order)

            time.sleep(0.2)

        # Override json file with empty list
        with open("bot_agents.json", "w", encoding='utf-8') as f:
            json.dump([], f)

        return close_orders

    def get_tradeable_markets(self):
        client = self.client
        markets = client.public.get_markets()

        for market in markets.data["markets"].keys():
            market_info = markets.data["markets"][market]
            if market_info["status"] == "ONLINE" and market_info["type"] == "PERPETUAL":
                self.tradeable_markets.append(market)
            if TEST_MODE and len(self.tradeable_markets) >= TEST_MODE_MARKET_LENGTH:
                break

    def get_candles_recent(self, market, sort="DESC", close_prices_only=True):
        candles = self.client.public.get_candles(
            market=market,
            resolution=RESOLUTION,
            limit=100
        ).data['candles']
        candles.sort(key=lambda x: x["startedAt"],
                     reverse=sort == "DESC")
        if close_prices_only:
            # '2023-08-13T01:00:00.000Z'
            return [
                {'datetime': datetime.strptime(candle['startedAt'], '%Y-%m-%dT%H:%M:%S.%fZ'),
                 'close': float(candle['close'])}
                for candle in candles
            ]

        return candles

    def get_candles_historical(self, market):
        timestamps = get_iso_timestamps()
        close_prices = []

        for _, timeframe in timestamps.items():
            from_time = timeframe["from_iso"]
            to_time = timeframe["to_iso"]

            candles = self.client.public.get_candles(
                market=market,
                resolution=RESOLUTION,
                from_iso=from_time,
                to_iso=to_time,
                limit=100
            )

            for candle in candles.data["candles"]:
                close_prices.append({
                    "datetime": datetime.strptime(candle['startedAt'], '%Y-%m-%dT%H:%M:%S.%fZ'),
                    market: float(candle["close"])
                })
        # return close_prices sorted by datetime
        return sorted(close_prices, key=lambda x: x["datetime"])

    @on_error_abort
    def construct_market_prices(self):
        self.get_tradeable_markets()

        close_prices = [self.get_candles_historical(
            market) for market in self.tradeable_markets]

        list_of_df = [pd.DataFrame(cp).set_index("datetime")
                      for cp in close_prices]
        df = (pd.concat(list_of_df, axis=1)
              .dropna(axis=1, how='any')
              )
        self.df_market_prices = df

    def store_cointegration_results(self):
        self.criteria_met_pairs = []
        df_market_prices = self.df_market_prices
        # Get all possible pairs of columns using itertools
        column_pairs = list(itertools.combinations(
            df_market_prices.columns, 2))

        for column_pair in column_pairs:
            # Check cointegration for each pair
            base = column_pair[0]
            quote = column_pair[1]
            series1 = df_market_prices[base].values.astype(float).tolist()
            series2 = df_market_prices[quote].values.astype(float).tolist()
            coint_flag, hedge_ratio, half_life = calculate_cointegration(
                series1, series2)
            if coint_flag == 1 and (0 < half_life <= MAX_HALF_LIFE):
                self.criteria_met_pairs.append({
                    "base_market": base,
                    "quote_market": quote,
                    "hedge_ratio": hedge_ratio,
                    "half_life": half_life,
                })
        # Create and save DataFrame
        pd.DataFrame(self.criteria_met_pairs).to_csv("cointegrated_pairs.csv")
        print(
            f'saved {len(self.criteria_met_pairs)} pairs to cointegrated_pairs.csv')

    def get_order_status(self, order_id):
        client = self.client
        order = client.private.get_order_by_id(order_id)
        return order.data["order"]["status"]

    def check_is_order_filled(self, order_id):
        order_status = self.get_order_status(order_id)
        if order_status == "FILLED":
            return True
        return False

    def run(self):
        # if ABORT_ALL_POSITIONS:
        #     self.abort_all_positions()

        if FIND_COINTEGRATED:
            self.construct_market_prices()
            self.store_cointegration_results()


if __name__ == '__main__':
    bot = TradingBot()
    # bot.run()
    candles_data = bot.get_candles_recent('BTC-USD')
    print(candles_data)
