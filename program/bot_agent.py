import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from dydx3.constants import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED

from program.decorate import on_error_abort
from program.trading_bot import TradingBot

logging.basicConfig(filename='bot.log',
                    format='%(asctime)s-%(process)d-%(levelname)s-%(message)s',
                    level=logging.DEBUG)


class CustomOrderStatus(Enum):
    LIVE = "live"
    FAILED = "failed"
    ERROR = "error"


class Market(Enum):
    MARKET_1 = "market_1"
    MARKET_2 = "market_2"


@dataclass
class OrderTracker:
    market_1: str
    market_2: str
    hedge_ratio: float
    z_score: float
    half_life: float
    order_id_m1: str
    order_m1_size: float
    order_m1_side: str
    order_time_m1: str
    order_id_m2: str
    order_m2_size: float
    order_m2_side: str
    order_time_m2: str
    pair_status: str
    comments: str


class OrderNotFilledException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class BotAgent:
    def __init__(self,
                 trading_bot: TradingBot,
                 order_tracker: OrderTracker,
                 base_price: float,
                 quote_price: float,
                 accept_failsafe_base_price: float
                 ):
        self.trading_bot = trading_bot
        self.client = trading_bot.client
        self.order_tracker = order_tracker
        self.base_price = base_price  # m1
        self.quote_price = quote_price  # m2
        self.accept_failsafe_base_price = accept_failsafe_base_price

    def check_order_status(self, order_id):

        bot = self.trading_bot
        tracker = self.order_tracker
        market_1, market_2 = self.order_tracker.market_1, self.order_tracker.market_2

        for _ in range(2):
            order_status = bot.get_order_status(order_id)

            print(order_status)

            if order_status == ORDER_STATUS_CANCELED:
                logging.info(
                    "%s vs %s - Order cancelled...", tracker.market_1, tracker.market_2)
                self.order_tracker.pair_status = "FAILED"
                return CustomOrderStatus.FAILED

            if order_status == ORDER_STATUS_FILLED:
                logging.info(
                    "%s vs %s - Order filled...", tracker.market_1, tracker.market_2)
                self.order_tracker.pair_status = "FILLED"
                return CustomOrderStatus.LIVE

            time.sleep(15)

        order_status = bot.get_order_status(order_id)

        if order_status != ORDER_STATUS_FILLED:
            self.client.private.cancel_order(order_id=order_id)
            self.order_tracker.pair_status = "ERROR"
            logging.info("%s vs %s - Order error...",
                         market_1, market_2)
            logging.info(
                "%s vs %s - Actual Status = %s", market_1, market_2, order_status)
            return CustomOrderStatus.ERROR

        return CustomOrderStatus.LIVE

    def open_trade(self, m1_or_m2: Market):

        place_market_order = self.client.private.create_market_order
        tracker = self.order_tracker

        market, order_id_attr, order_time_attr, price, side, size = self.get_market_obj(
            m1_or_m2)

        try:
            order = place_market_order(
                self.client,
                market=market,
                side=side,
                size=size,
                price=price,
                reduce_only=False
            )

            setattr(tracker, order_id_attr, order['order']['id'])
            setattr(tracker, order_time_attr,
                    datetime.now().strftime("%H:%M:%S"))

        except Exception as e:

            tracker.pair_status = "ERROR"
            comments = f"Market 1 {market} - {e}."
            tracker.comments = comments
            raise e

    def get_market_obj(self, m1_or_m2):
        tracker = self.order_tracker
        match m1_or_m2:
            case Market.MARKET_1:
                market = tracker.market_1
                side = tracker.order_m1_side
                size = tracker.order_m1_size
                price = self.base_price
                order_id_attr = "order_id_m1"
                order_time_attr = "order_time_m1"

            case Market.MARKET_2:
                market = tracker.market_2
                side = tracker.order_m2_side
                size = tracker.order_m2_size
                price = self.quote_price
                order_id_attr = "order_id_m2"
                order_time_attr = "order_time_m2"

            case _:
                raise ValueError('m1_or_m2 must be either m1 or m2')
        return market, order_id_attr, order_time_attr, price, side, size

    def open_trade_and_check(self, m1_or_m2: Market, on_error_func: callable | None):
        tracker = self.order_tracker
        market, order_id_attr, _, price, side, size = self.get_market_obj(
            m1_or_m2)
        logging.info('%s : Placing order...', market)
        logging.info('Side: %s, Size: %s, Price: %s',
                     side, size, price)
        self.open_trade(m1_or_m2)
        order_status = self.check_order_status(
            getattr(tracker, order_id_attr))
        if order_status != CustomOrderStatus.LIVE:
            logging.info('%s : Order failed. ', market)
            self.order_tracker.pair_status = 'ERROR'
            self.order_tracker.comments = f"{market}: Order failed."
            if on_error_func is not None:
                on_error_func()
            return False
        return True

    def open_trades(self):
        if self.open_trade_and_check(Market.MARKET_1, None):
            self.open_trade_and_check(Market.MARKET_2, self.close_order_m1)

    @on_error_abort
    def close_order_m1(self):
        tracker = self.order_tracker
        market, _, _, _, side, size = self.get_market_obj(Market.MARKET_1)
        close_order = self.client.private.place_market_order(
            self.client,
            market=market,
            side=side,
            size=size,
            price=self.accept_failsafe_base_price,
            reduce_only=True
        )
        order_status = self.check_order_status(close_order['order']['id'])
        if order_status != CustomOrderStatus.LIVE:
            logging.info('Closed Order M1.')
            return
        tracker.comments = f"{market}: Order failed. Could not close order M1."
        tracker.pair_status = "ERROR"
        raise OrderNotFilledException(
            f"Could not close order M1 for {market}.")
