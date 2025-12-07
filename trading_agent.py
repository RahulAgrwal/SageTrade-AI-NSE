import json
import copy
import random
import sys
import time
from threading import Timer
from config import NSE_STOCKS, AGENT_CONFIG, DATABASE_CONFIG, UPSTOX_CONFIG,DECISION_CHART_PLOT_CONFIG
from flask_api import FlaskAPI
from gemini_llm_integration import GeminiLLMClient
from intraday_technical_analyzer import IntradayAnalyzer
from logger_config import get_logger
from news_fetcher import NewsFetcher
from nse_500_fetcher import NSE500Fetcher
from plot_graph_of_stock import StockChartAnalyzer
from postgres_database import PostgresDatabase
from upstox_wrapper import UpstoxClient
from llm_integration import LLMClient
from risk_manager import RiskManager
from datetime import datetime, timedelta

logger = get_logger(__name__)
class TradingAgent:
    """
    The main trading agent that orchestrates the entire trading process.

    It connects the Upstox client, the LLM, and the Risk Manager to make
    and execute trading decisions based on real-time market data.
    """

    def __init__(self, llm_config, risk_config, agent_config, intraday_technical_config, news_api_config):
        """
        Initializes the TradingAgent.

        Args:
            upstox_config (dict): Configuration for the UpstoxClient.
            llm_config (dict): Configuration for the LLMClient.
            risk_config (dict): Configuration for the RiskManager.
            instruments (list[str]): List of instrument keys to trade.
        """
        self.upstox_clients = []
        self.llm_client = GeminiLLMClient()
        self.risk_manager = RiskManager(risk_config, agent_config)
        self.news_api_client = NewsFetcher(**news_api_config)
        self.nse_500_fetcher = NSE500Fetcher()
        self.db = PostgresDatabase()
        self.intraday_technical_config = intraday_technical_config
        self.product_type = agent_config['PRODUCT_TYPE']
        self.decision_interval = agent_config['DECISION_INTERVAL_SECONDS']
        self.leverage_on_intraday = agent_config['LEVERAGE_ON_INTRADAY']
        self.auto_pick_stock = agent_config['AUTO_PICK_STOCK']
        self.market_close_time = datetime.strptime(agent_config['MARKET_CLOSE_TIME'], '%H:%M').time()
        self.decision_timer = None 
        self.is_eod_squaring_off = False

    def start(self):
        """Starts the trading agent."""
        logger.info("Starting trading agent...")
        upstox_config = UPSTOX_CONFIG


        for config in upstox_config:
            upstox_client = UpstoxClient(**config)

            upstox_client.authenticate() # Authenticate User

            user_profile = upstox_client.get_profile()  # Get User Profile
            self.db.save_user_details(user_profile)

            upstox_client.get_user_fund_margin() # User Fund Margin

            upstox_client.connect_portofolio_data_streamer(self.update_portfolio_positions, self.save_order_details) # Connect to Profile Data Streamer

            self.upstox_clients.append(upstox_client)

        time.sleep(2)
        self.make_decision()

    def _start_decision_timer(self):
        """Starts a recurring timer to trigger the decision-making process."""
        if self.decision_timer:
            self.decision_timer.cancel()
        
        if not self.is_eod_squaring_off:
            self.decision_timer = Timer(self.decision_interval, self.make_decision)
            self.decision_timer.start()

    def on_market_data(self, message):
        """

        Callback function to handle incoming market data from the websocket.
        
        This method is the entry point for real-time data. For now, it just logs
        the data. The core logic is in `make_decision`.
        """
        # logger.info(f"Market data received: {message}")
        for instrument_key, feed_data in message.items():
            self.market_data[instrument_key] = feed_data
        # The data is also stored in self.market_data, which we'll use.
    def on_market_intraday_data(self, message):
        """

        Callback function to handle incoming market data from the websocket.
        
        This method is the entry point for real-time data. For now, it just logs
        the data. The core logic is in `make_decision`.
        """
        # logger.info(f"Market Intrday Day data received: {message}")
        for instrument_key, data in message.items():
            self.market_intraday_data[instrument_key] = data
        # The data is also stored in self.market_data, which we'll use.
    def make_decision(self):
        """
        The core logic loop: analyze data, get LLM decision, check risk, and execute.
        This function is called periodically by the timer.
        """
        now = datetime.now().time()
        if now >= self.market_close_time:
            if not self.is_eod_squaring_off:
                self.square_off_all_positions()
            return
        # Update Portfolio Positions
        for upstox_client in self.upstox_clients:
            portfolio_margin = upstox_client.get_user_fund_margin() # Get Portfolio Margin
            position_present = True
            all_positions, open_positions = self.get_portfolio_positions(upstox_client)
            instruments_to_trade = []
            if(open_positions == {}):
                position_present = False
                instruments_to_trade = self.get_instruments_to_trade(portfolio_margin)
            else:
                instrument_keys = list(open_positions.keys())
                for key in instrument_keys:                
                    instrument_to_trade = upstox_client.get_instrument_info_from_instrument_key(key)
                    if instrument_to_trade:
                        instruments_to_trade.append(instrument_to_trade)

            logger.info(f"Instruments to trade: {instruments_to_trade}")
            number_of_instruments_to_trade = len(instruments_to_trade)
            for instrument_to_trade in instruments_to_trade:
                logger.info(f"---------- Starting new decision cycle for {instrument_to_trade['trading_symbol']} ----------")
                start_time = datetime.now()
                trading_symbol = instrument_to_trade['trading_symbol']
                instrument_key = instrument_to_trade['instrument_key']
                stock_name = instrument_to_trade['name']
                logger.info(f"Instrument to Trade : {trading_symbol} : {instrument_key} : {stock_name}")
                market_data = upstox_client.get_full_market_quote(instrument_key)
                if market_data == {}:
                    logger.error("No market data received. Skipping cycle.")
                    pass 
                portfolio_margin = upstox_client.get_user_fund_margin()
                market_intraday_data = upstox_client.get_intra_day_candle_data(instrument_key) #Intraday Candle Data
                technical_summary = self.get_technical_summary(trading_symbol,market_data) #Technical Summary
                stock_news = self.news_api_client.get_company_news(stock_name) #Stock News
                all_positionss, open_positionss = self.get_portfolio_positions(upstox_client)
                position = {instrument_key: open_positionss.get(instrument_key, {})} # Latest Position Data for Instrument
                previous_decision = self.db.get_today_decisions_for_instrument(instrument_key)
                previous_decision_str = self.format_previous_decision(previous_decision) # Format previous_decision
                chart_plot_image_paths = self.get_chart_plot_image_paths(trading_symbol)
                logger.info(f"Previous Decision : {previous_decision_str}")
                logger.info(f"Instrument to Trade : {instrument_to_trade}")
                logger.info(f"Position Margin : {portfolio_margin}")
                logger.info(f"Current Position : {position}")
                logger.info(f"Market Data : {market_data}")
                # logger.info(f"Intraday Candle Data : {market_intraday_data_str}")
                logger.info(f"Technical Summary : {technical_summary}")
                logger.info(f"Stock News : {stock_news}")
                # Decision from LLM
                llm_json = None
                if not position_present:
                    llm_json = self.llm_client.generate_decision_for_new_trade(instrument_key, instrument_to_trade, market_data, market_intraday_data, portfolio_margin, position ,technical_summary, stock_news,previous_decision_str,number_of_instruments_to_trade,chart_plot_image_paths,all_positionss, self.leverage_on_intraday)
                else:
                    llm_json = self.llm_client.generate_decision_for_position_present(instrument_key, instrument_to_trade, market_data, market_intraday_data, portfolio_margin, position ,technical_summary, stock_news,previous_decision_str,number_of_instruments_to_trade,chart_plot_image_paths,all_positionss, self.leverage_on_intraday)

                self.db.save_llm_decision(llm_json)
                llm_decision = llm_json['response']
                if not llm_decision or 'action' not in llm_decision:
                    logger.error("Invalid or empty decision from LLM. Skipping cycle.")
                    pass # Restart timer for next cycle

                action = llm_decision.get('action')
                instrument_key = llm_decision.get('instrument_key')
                current_price = llm_decision.get('current_price',0.0)

                logger.info(f"LLM Decision for {instrument_key}: {action}. Thought: {llm_decision.get('thought')} at price ~{current_price}")
                # Process trade decisions
                if llm_decision and self.risk_manager.validate_decision(llm_decision, portfolio_margin, current_price):
                    if current_price:
                         quantity = llm_decision.get('quantity', 0)
                         self.execute_trade(upstox_client, llm_decision, current_price, quantity)
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.info(f"---------- Decision cycle completed for {trading_symbol} : {instrument_key} : {stock_name} in {duration} seconds----------")
                number_of_instruments_to_trade-=1
                time.sleep(5)

        now = datetime.now()
        next_decision_time = now + timedelta(seconds=self.decision_interval)
        next_decision_time = next_decision_time.strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"---------- Next Decision in {self.decision_interval} seconds at {next_decision_time} ----------")
        self._start_decision_timer()

    def execute_trade(self,upstox_client, decision, price, quantity):
        """Executes a trade based on the validated decision."""
        instrument = decision['instrument_key']
        action = decision['action']
        order_type = decision['order_type']
        stop_loss = decision.get('stop_loss') or 0.0
        take_profit = decision.get('take_profit') or 0.0

        
        if action == 'BUY':
            logger.info(f"Executing INTRADAY BUY for {quantity} of {instrument} at ~{price}")
            self.execute_buy(upstox_client, instrument,quantity, price, order_type, stop_loss,take_profit )
            
            

        elif action == 'SELL':
            logger.info(f"Executing INTRADAY SELL for {quantity} of {instrument} at ~{price}")
            self.execute_sell(upstox_client, instrument, quantity, price, order_type,stop_loss, take_profit)

    def execute_buy(self,upstox_client, instrument_key, quantity, price, order_type, stop_loss,take_profit ):
        """Handles the logic for Buying a position and updating the portfolio_margin."""
            # Check if we already have a position
        if not price:
            logger.error(f"Cannot execute BUY for {instrument_key}, no price data.")
            return

        logger.info(f"Executing BUY for {quantity} of {instrument_key} at ~{price}")
        order_result = upstox_client.place_order(instrument_key, quantity, 'BUY', order_type , price, 'I', 'DAY', stop_loss,take_profit)

    def execute_sell(self,upstox_client, instrument_key, quantity, price, order_type, stop_loss,take_profit ):
        """Handles the logic for selling a position and updating the portfolio_margin."""
        if not price:
            logger.error(f"Cannot execute sell for {instrument_key}, no price data.")
            return

        logger.info(f"Executing SELL for {quantity} of {instrument_key} at ~{price}")
        order_result = upstox_client.place_order(instrument_key, quantity, 'SELL', order_type , price, 'I', 'DAY', stop_loss,take_profit)
        

    def stop(self):
        """Stops the trading agent and disconnects services."""
        logger.info("Stopping trading agent...")
        if self.decision_timer:
            self.decision_timer.cancel()

        logger.info("Trading agent stopped. Exiting program...")
        sys.exit(0)
    def update_portfolio_positions(self, positions_data):
        """Update portfolio_positions with positions data"""
        try:
            if positions_data:
                logger.info(f"Portfolio positions : {positions_data}")
        except Exception as e:
            logger.error(f"Error updating portfolio_positions positions: {e}")
    
    
    def get_portfolio_positions(self, upstox_client):
        """Update portfolio_positions with positions data"""
        try:
            all_positions_data = upstox_client.get_positions()
            open_positions_dic = {}
            if all_positions_data:
                for pos in all_positions_data:
                    if pos.quantity != 0 and pos.product=="I":
                        instrument_token = pos.instrument_token
                        open_positions_dic[instrument_token] = pos
                        logger.info(f"Updated portfolio open position for {instrument_token}: {pos}")
            return all_positions_data,open_positions_dic
        except Exception as e:
            logger.error(f"Error updating portfolio_positions positions: {e}")
            return {}

    def square_off_all_positions(self):
        """Closes all open positions before market close."""
        logger.warning("MARKET CLOSING SOON. Squaring off all open positions.")
        self.is_eod_squaring_off = True
        if self.decision_timer:
            self.decision_timer.cancel()
        for upstox_client in self.upstox_clients:
            upstox_client.exit_all_positions()
        self.stop()

    def auto_pick_instrument_to_trade(self, upstox_client, portfolio_margin):
        nse_instrument_keys = self.nse_500_fetcher.get_instrument_list()   
        nse_instrument_keys_str = ",".join(nse_instrument_keys[:499]) 
        ltp_data = upstox_client.get_last_trading_price(nse_instrument_keys_str,"v3")
        logger.info(f"Fetched LTP of {len(ltp_data)} Stocks")

        affordable_instruments = []
        for key, value in ltp_data.items():
            if value.last_price <= portfolio_margin['available_margin']:
                instrument ={
                    "instrument_key": value.instrument_token,
                    "last_price": value.last_price,
                    "stock_name": key.split(":")[1]
                }
                affordable_instruments.append(instrument)
        affordable_instruments = sorted(affordable_instruments, key=lambda x: x['last_price'], reverse=True)
        logger.info(f"Affordable instruments for user {upstox_client.user_profile['user_name']}: {len(affordable_instruments)}")

        stocks_to_compare = []
        number_of_stocks_to_compare = AGENT_CONFIG["SELECT_STOCK_COUNT_TO_COMPARE"]
        if(AGENT_CONFIG["RANDOM_SELECT_STOCKS"]):
            stocks_to_compare = random.sample(affordable_instruments, min(number_of_stocks_to_compare, len(affordable_instruments)))
        else:
            stocks_to_compare = affordable_instruments[:number_of_stocks_to_compare]

        logger.info(f"Getting {number_of_stocks_to_compare} stocks to compare : {stocks_to_compare}")
        technical_summaries = []
        for index, instrument in enumerate(stocks_to_compare, 1):
            full_market_data = upstox_client.get_full_market_quote(instrument['instrument_key'])
            technical_summary =  self.get_technical_summary(instrument['stock_name'], full_market_data)
            technical_summary['instrument_key'] = instrument['instrument_key']
            chart_plot_image_path = self.get_chart_plot_image_path_for_stock_selection(instrument['stock_name'])
            technical_summary['chart_plot_image_path'] = chart_plot_image_path
            technical_summary['index'] = index
            technical_summaries.append(technical_summary)
        
        stock_to_trade = self.llm_client.get_instrument_to_trade(technical_summaries)
        instrument_to_trades = []
        for stock in stock_to_trade:
            instrument_to_trade = {
                "instrument_key": stock["instrument_key"],
                "trading_symbol": stock["stock_name"],
                "name": stock["stock_name"],
                "last_price" : stock["last_price"],
                "confidence_score" : stock["confidence_score"],
                "thought" : stock["thought"]
            }
            instrument_to_trades.append(instrument_to_trade)
        return instrument_to_trades
    
    def get_instruments_to_trade(self, portfolio_margin):
        upstox_client = self.upstox_clients[0]
        if self.auto_pick_stock:
            logger.info("Auto-picking stock...")
            return self.auto_pick_instrument_to_trade(upstox_client, portfolio_margin)
        else:
            return upstox_client.get_instrument_info_from_stock(NSE_STOCKS[0])

    def get_technical_summary(self, stock_name, full_market_data=None):
        technical_analyzer = IntradayAnalyzer(stock_name, self.intraday_technical_config['PERIOD'], self.intraday_technical_config['INTERVAL'])
        technical_summary = technical_analyzer.get_intraday_summary()
        technical_analyzer.cleanup()
        if full_market_data:
            key = f"NSE_EQ:{stock_name}"
            data_for_stock = full_market_data.get(key, {})
            technical_summary["total_volume"] = data_for_stock.get('volume', 0)
            technical_summary["average_price"] = data_for_stock.get('average_price', 0)
            technical_summary["net_change"] = data_for_stock.get('net_change', 0)
            technical_summary["total_buy_quantity"] = data_for_stock.get('total_buy_quantity', 0)
            technical_summary["total_sell_quantity"] = data_for_stock.get('total_sell_quantity', 0)
            technical_summary["lower_circuit_limit"] = data_for_stock.get('lower_circuit_limit', 0)
            technical_summary["upper_circuit_limit"] = data_for_stock.get('upper_circuit_limit', 0)
        logger.info(f"Technical summary for {stock_name}: {technical_summary}")
        return technical_summary
    
    def get_chart_plot_image_path_for_stock_selection(self, stock_name):
        chart = StockChartAnalyzer(stock_name, self.intraday_technical_config['PERIOD'], self.intraday_technical_config['INTERVAL'])
        chart.generate_chart()
        file_name = chart.get_chart_file_name()
        chart.destroy()
        return file_name
    
    def get_chart_plot_image_paths(self, stock_name):
        image_paths = []
        for config in DECISION_CHART_PLOT_CONFIG:
            chart = StockChartAnalyzer(stock_name, config['PERIOD'], config['INTERVAL'])
            chart.generate_chart()
            file_name = chart.get_chart_file_name()
            image_paths.append(file_name)
            chart.destroy()
        return image_paths
    
    def save_order_details(self, order_details_dict):
        try:
            # Save Order Details
            self.db.save_order_details(order_details_dict)
        except Exception as e:
            logger.error(f"Error saving order details: {e}")

    def format_previous_decision(self, previous_decisions):
        readable = "\n\n".join([
            "-------------\n"
            f"Decision Time: {d['decision_on']}\n"
            f"Action: {d['action']}\n"
            f"Stock Price: ₹{d['stock_price']}\n"
            f"Stop Loss: ₹{d.get('stop_loss')}\n"
            f"Take Profit: ₹{d.get('take_profit')}\n"
            f"Thought: {d['thought']}"
            for d in previous_decisions
        ])
        return readable


