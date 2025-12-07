import os
import json
import re
import mimetypes
from datetime import datetime
from time import time
from google import genai
from google.genai import types

# Import your existing config and logger
from config import INTRADAY_TECHNICAL_ANALYZER_CONFIG, LLM_PRICING, RISK_CONFIG, AGENT_CONFIG, GEMINI_LLM_CONFIG
from logger_config import get_logger
from prompts import SYSTEM_PROMPT_NEW_TRADE_EXECUTION, SYSTEM_PROMPT_POSITION_PRESENT, SYSTEM_PROMPT_STOCK_TO_TRADE

logger = get_logger(__name__)
JSON_REQ_RES_DIR = "llm_json_req_res"

class GeminiLLMClient:
    """
    Client for interacting with Google's Gemini models via the google-genai SDK.
    
    This class formats prompts, handles multimodal input (images), and parses 
    structured JSON responses to extract trading decisions.
    """

    def __init__(self):
        """
        Initializes the Gemini client.
        """
        if not GEMINI_LLM_CONFIG.get('api_key'):
            raise ValueError("LLM API key not provided.")
        
        # Initialize Google GenAI Client
        self.client = genai.Client(api_key=GEMINI_LLM_CONFIG['api_key'])
        
        # Configuration mapping
        self.model = GEMINI_LLM_CONFIG['model']
        self.temperature = GEMINI_LLM_CONFIG.get('temperature', 0.1)
        self.model_for_stock_selection = GEMINI_LLM_CONFIG['model_for_stock_selection']
        self.model_for_stock_qty_selection = GEMINI_LLM_CONFIG['model_for_stock_qty_selection']
        self.training_pdf_part = self._load_pdf_part("training/NSE_Training_Framework_for_AI_Models.pdf")   
        # self.training_video_part = self._load_video_part("https://youtu.be/jvzd7UPlb5Y?si=AVjpdE7dR0uhwPBE") 
                
        os.makedirs(JSON_REQ_RES_DIR, exist_ok=True)

    def _load_image_part(self, image_path: str):
        """
        Reads a local image and converts it into a GenAI Part object.
        """
        try:
            if not os.path.exists(image_path):
                logger.warning(f"Image not found at: {image_path}")
                return None
            
            # Guess mime type
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                mime_type = "image/png"

            with open(image_path, "rb") as f:
                image_bytes = f.read()

            return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        except Exception as e:
            logger.error(f"Error loading image part: {e}")
            return None

    def _load_pdf_part(self, pdf_path: str):
        """
        Reads a local PDF and converts it into a GenAI Part object.
        """
        try:
            if not os.path.exists(pdf_path):
                logger.warning(f"PDF not found at: {pdf_path}")
                return None
            
            # PDF MIME type is standard, but you can use mimetypes.guess_type if preferred
            mime_type = "application/pdf"

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            # Create the Part object using the same from_bytes method
            return types.Part.from_bytes(data=pdf_bytes, mime_type=mime_type)
            
        except Exception as e:
            logger.error(f"Error loading PDF part: {e}")
            return None
    
    def _load_video_part(self, url_link: str):
        """
        Reads a Youtube Video and converts it into a GenAI Part object.
        """
        try:
            return types.Part(
                file_data=types.FileData(file_uri=url_link)
            )
            
        except Exception as e:
            logger.error(f"Error loading PDF part: {e}")
            return None

    def generate_decision_for_new_trade(self, instrument_key: str, instrument_to_trade: str, market_data_str: str, market_intraday_data_str: str, portfolio_margin_status_str: str, portfolio_position_status_str: str, technical_summary: str, stock_news: str, previous_decision, number_of_instruments_to_trade, chart_plot_image_paths,all_positionss, leverage_on_intraday: int = 1) -> dict | None:
        """
        Sends the current market and portfolio data to the LLM and gets a trading decision.
        """
        user_data_prompt = f"""
        ### Trading Data Input

        **Stock to Trade:** {instrument_to_trade}

        **Portfolio and Risk Constraints:**
        * Leverage on Intraday: {AGENT_CONFIG["LEVERAGE_ON_INTRADAY"]}x
        * Risk_Percentage: {RISK_CONFIG["RISK_PERCENTAGE_FOR_SINGLE_TRADE"]}%
        * Portfolio Margin: {portfolio_margin_status_str}
        * All Positions: {all_positionss}

        **Time Context:**
        * Current Time: {datetime.now().strftime("%H:%M:%S")} IST
        * Market Close Time: {AGENT_CONFIG["MARKET_CLOSE_TIME"]} IST

        **Current Market Data (JSON):**
        ```json
        {market_data_str}

        **Intraday Candles Data (JSON):**
        ```json
        {market_intraday_data_str}

        **Technical Summary (JSON):**
        ```json
        {technical_summary}

        **Previous Decisions:**
        {previous_decision}

        **Latest News (JSON):**
        ```json
        {stock_news}

        **Existing Portfolio Positions(JSON):**
        ```json
        {portfolio_position_status_str}
        """

        user_question_prompt = """
        ***
        # TRADING DECISION GENERATION MANDATE

        You are a quantitative trading analyst. Your task is to perform a rigorous analysis based on the provided documents (training PDF, chart plots), market data, and portfolio status, and then output a decision in the required JSON format.

        ## 1. Position and Risk Assessment
        * **Evaluate Existing Position:** Analyze the 'All Positions' and 'Previous Decisions' against the 'Current Market Data'. Determine if the existing position should be *maintained*, *closed for profit*, or *closed due to risk* (Stop Loss breached).
        * **Constraint Check:** Based on 'Portfolio Margin' and 'Leverage on Intraday', assess the **maximum available capital** for a new trade. Ensure the final decision respects the 'Risk_Percentage' for a single trade.

        ## 2. Technical and Fundamental Analysis
        * **Technical Outlook:** Use the 'Technical Summary' and 'Chart Plots' to determine the short-term trend, key support, and resistance levels.
        * **News Impact:** Analyze the 'Latest News' for potential fundamental catalysts that may override technical signals or increase volatility.

        ## 3. Decision Formulation
        * **Determine Action:** Based on the full analysis (Steps 1 & 2), select the optimal action: **BUY**, **SELL**, or **HOLD**.
        * **Calculate Sizing and Price:** If BUY or SELL, calculate the **quantity** that respects the risk constraints. Determine the optimal **Stop Loss** and **Target Price** based on technical levels.

        ## 4. Final Output Requirement
        Provide your response strictly and exclusively in the specified **JSON format**. The **'reasoning' field MUST detail the analysis from Steps 1, 2, and 3.**
        ***
        """

        logger.info("================Generating LLM decision======================")
        image_parts =[]
        for chart_plot_image_path in chart_plot_image_paths:
            logger.info(f"Attaching chart image for LLM: {chart_plot_image_path}")
            image_part = self._load_image_part(chart_plot_image_path)
            if not image_part:
                logger.error("Skipping decision generation due to missing image.")
                return None
            image_parts.append(image_part)


        try:
            # FIX: 'system' role is removed from here
            contents = [
                types.Content(role="user", parts=[types.Part.from_text(text=user_data_prompt)]),
                types.Content(role="model", parts=[types.Part.from_text(text="I understand. I'll analyze the data and provide a trading decision in the specified JSON format.")]),
                types.Content(role="user", parts=[
                    types.Part.from_text(text=user_question_prompt),
                    self.training_pdf_part,
                    *image_parts
                ])
            ]

            # FIX: System prompt goes here
            config = types.GenerateContentConfig(
                temperature=self.temperature,
                response_mime_type="application/json",
                system_instruction=[types.Part.from_text(text=SYSTEM_PROMPT_NEW_TRADE_EXECUTION)]
            )

            response = self._generate_content_wrapper(self.model_for_stock_qty_selection, contents, config)
            
            decision_str = response.text
            logger.info(f"***************LLM DECISION***************: \n{decision_str}")
            
            decision_json = json.loads(decision_str)

            usage = response.usage_metadata
            if usage:
                cost = self.calculate_cost(self.model_for_stock_qty_selection, usage)
                logger.info(f"====Cost Breakdown====\n{json.dumps(cost)}")
                decision_json["cost_info"] = cost

            json_to_save = {
                "request": [c.role for c in contents], 
                "response": decision_json
            }
            self.create_json_file(json_to_save, instrument_key)

            return json_to_save
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode LLM JSON response: {e}")
            return None
        except Exception as e:
            logger.error(f"An error occurred while communicating with the LLM: {e}")
            return None
        
    def generate_decision_for_position_present(self, instrument_key: str, instrument_to_trade: str, market_data_str: str, market_intraday_data_str: str, portfolio_margin_status_str: str, portfolio_position_status_str: str, technical_summary: str, stock_news: str, previous_decision, number_of_instruments_to_trade, chart_plot_image_paths,all_position, leverage_on_intraday: int = 1) -> dict | None:
        """
        Sends the current market and portfolio data to the LLM for an existing position.
        """
        user_data_prompt = f"""
        ### 📊 TRADING CONTEXT AND CONSTRAINTS
        
        * **Instrument to Analyze:** {instrument_to_trade}
        * **Instrument Key:** {instrument_key}
        * **Number of Intruments to Trade Today (Max):** {number_of_instruments_to_trade}
        * **Leverage on Intraday:** {AGENT_CONFIG["LEVERAGE_ON_INTRADAY"]}x
        * **Risk Percentage per Trade:** {RISK_CONFIG["RISK_PERCENTAGE_FOR_SINGLE_TRADE"]}%
        
        ---
        ### ⏰ TIME CONTEXT
        
        * **Current Time (IST):** {datetime.now().strftime("%H:%M:%S")}
        * **Market Close Time (IST):** {AGENT_CONFIG["MARKET_CLOSE_TIME"]}
        * **Decision Interval (Seconds):** {AGENT_CONFIG["DECISION_INTERVAL_SECONDS"]}
        
        ---
        ### 💰 PORTFOLIO & POSITION STATUS
        
        **Portfolio Margin Status(JSON):**
        ```json
        {portfolio_margin_status_str}

        **Existing Portfolio Positions(JSON):**
        ```json
        {portfolio_position_status_str}

        **All Positions(JSON):**
        ```json
        {all_position}

        ---
        ### 📈 MARKET & TECHNICAL DATA
        ** Current Market Snapshot (JSON):**
        ```json
        {market_data_str}

        ** Intraday Candles Data (JSON):**
        ```json
        {market_intraday_data_str}

        **Technical Analysis Summary (JSON):**
        ```json
        {technical_summary}

        **Latest Relevant News (JSON):**
        ```json
        {stock_news}
        ---
        ### 📜 HISTORY
        **Previous Decisions Made:**
        {previous_decision}
        ---
        """

        user_question_prompt = """
        ### POSITION MANAGEMENT MANDATE
        Perform a comprehensive analysis using the training PDF, chart plots, and current data:

        1.  **Risk Check:** Is the current price challenging the Stop-Loss or Take-Profit?
        2.  **Time Check:** Does the time to market close mandate an immediate closure?
        3.  **Strategy Alignment:** Does the chart visually support the continuation (ADD/HOLD) or demand closure (EXIT) based on the principles in the Training PDF?

        Based on this analysis, determine the single most optimal action: **BUY**, **SELL**, or **HOLD**. (Remember: BUY/SELL is used for closing *or* scaling in, depending on the current position's side.)

        Provide your response strictly in the JSON format defined by the System Prompt.
        """

        image_parts =[]
        for chart_plot_image_path in chart_plot_image_paths:
            logger.info(f"Attaching chart image for LLM: {chart_plot_image_path}")
            image_part = self._load_image_part(chart_plot_image_path)
            if not image_part:
                logger.error("Skipping decision generation due to missing image.")
                return None
            image_parts.append(image_part)

        logger.info("================Generating LLM decision for existing position======================")
        
        try:
            contents = [
                types.Content(role="user", parts=[types.Part.from_text(text=user_data_prompt)]),
                types.Content(role="model", parts=[types.Part.from_text(text="I acknowledge the existing position context, previous decisions, and all financial data. I will analyze P&L, exposure, technicals, and time constraints to generate a management decision in strict JSON format.")]),
                types.Content(role="user", parts=[
                    types.Part.from_text(text=user_question_prompt),
                    self.training_pdf_part,
                    *image_parts
                ])
            ]

            # FIX: System prompt added to config
            config = types.GenerateContentConfig(
                temperature=self.temperature,
                response_mime_type="application/json",
                system_instruction=[types.Part.from_text(text=SYSTEM_PROMPT_POSITION_PRESENT)]
            )

            response = self._generate_content_wrapper(self.model, contents, config)
            decision_str = response.text
            logger.info(f"***************LLM DECISION FOR EXISTING POSITION***************: \n{decision_str}")

            decision_json = json.loads(decision_str)

            usage = response.usage_metadata
            if usage:
                cost = self.calculate_cost(self.model, usage)
                decision_json["cost_info"] = cost

            json_to_save = {"request": "Existing Position Analysis", "response": decision_json}
            self.create_json_file(json_to_save, instrument_key)

            return json_to_save

        except Exception as e:
            logger.error(f"Error in existing position decision: {e}")
            return None
        
    def get_instrument_to_trade(self, technical_summaries) -> dict:
        """
        Analyzes multiple stocks to select the best one to trade.
        """
        logger.info("================Generating LLM decision for instrument to trade======================")

        intro_prompt = f"""
        Parse the training pdf,chart plots provided, current and prevoius position, current market data to evaluate the existing position.
        Carefully Analyze the technical summaries of multiple stocks provided below with chart Plots.
        Some key considerations:
            - Current Time: {datetime.now().strftime("%H:%M:%S")} IST
            - Market Close Time: {AGENT_CONFIG["MARKET_CLOSE_TIME"]} IST  
            - Number of Stocks to select: {AGENT_CONFIG["NUMBER_OF_STOCKS_TO_TRADE"]}
            - Technical Indicator Configuration : {INTRADAY_TECHNICAL_ANALYZER_CONFIG}
                
        Provide your response strictly in JSON format.
        """
        
        try:
            user_parts = [types.Part.from_text(text=intro_prompt)]
            
            for technical_summary in technical_summaries:
                stock_text = f"===Stock {technical_summary['index']}===\n{technical_summary}"
                user_parts.append(types.Part.from_text(text=stock_text))
                
                img_part = self._load_image_part(technical_summary['chart_plot_image_path'])
                logger.info(f"Attaching chart image for LLM: {technical_summary['chart_plot_image_path']}")
                if img_part:
                    user_parts.append(img_part)
            user_parts.append(self.training_pdf_part)
            # FIX: 'system' role removed from contents
            contents = [
                types.Content(role="user", parts=user_parts)
            ]

            # FIX: System prompt added to config
            config = types.GenerateContentConfig(
                temperature=self.temperature,
                response_mime_type="application/json",
                system_instruction=[types.Part.from_text(text=SYSTEM_PROMPT_STOCK_TO_TRADE)]
            )

            response = self._generate_content_wrapper(self.model_for_stock_selection, contents, config)
            
            decision_str = response.text
            logger.info(f"***************STOCK TO TRADE*************** \n{decision_str}")

            decision_json = json.loads(decision_str)

            usage = response.usage_metadata
            if usage:
                cost = self.calculate_cost(self.model_for_stock_selection, usage)
                logger.info(f"====Cost Breakdown====\n{json.dumps(cost)}")
                decision_json["cost_info"] = cost

            self.create_json_file({"response": decision_json})

            return decision_json.get("results")
            
        except Exception as e:
            logger.error(f"Error in stock selection: {e}")
            return None
   
    def get_image_analysis_response(self, image_path: str, instruction: str = "Analyze this chart and describe key insights. Learn From Trainig Youtube Video and PDF Provided.") -> str | None:
        """
        Sends an image to Gemini for analysis.
        """
        try:
            logger.info(f"Sending image for analysis: {image_path}")
            
            image_part = self._load_image_part(image_path)
            if not image_part:
                return None

            prompt_contents = [
                types.Content(role="user", parts=[
                    self.training_pdf_part,
                    types.Part.from_text(text=instruction),
                    image_part
                ])
            ]
            
            # Using basic generation, no JSON strict enforcement unless instruction demands it
            response = self.client.models.generate_content(
                model=self.model_for_stock_qty_selection,
                contents=prompt_contents,
                config=types.GenerateContentConfig(temperature=self.temperature)
            )
            logger.info(f"Response : {response}")
            result_text = response.text
            logger.info(f"===== LLM Image Analysis Response =====\n{result_text}")
            logger.info(f"===== LLM response.usage_metadata =====\n{response.usage_metadata}")
            cost = self.calculate_cost(self.model_for_stock_qty_selection, response.usage_metadata)
            logger.info(f"====Cost Breakdown====\n{json.dumps(cost)}")
            self.create_json_file({"response": result_text})
            return result_text

        except Exception as e:
            logger.error(f"Error while sending image to LLM: {e}")
            return None

    def _execute_llm_call(self, model: str, contents: list, file_prefix: str) -> dict | None:
        """
        Internal helper to execute the API call, handle JSON parsing, logging, and costing.
        """
        try:
            # API Call with JSON enforcement
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature
                )
            )

            decision_str = response.text
            logger.info(f"***************LLM RESPONSE ({file_prefix})***************: \n{decision_str}")
            
            decision_json = json.loads(decision_str)

            # Cost Calculation
            usage = response.usage_metadata
            cost = {}
            if usage:
                cost = self.calculate_cost(model, usage)
                logger.info(f"====Cost Breakdown====\n{json.dumps(cost)}")
                decision_json["cost_info"] = cost

            serialized_request = []
            for c in contents:
                parts = []
                for p in c.parts:
                    if p.text:
                        parts.append({"type": "text", "text": p.text})
                    else:
                        parts.append({"type": "image", "info": "Binary Image Data"})
                serialized_request.append({"role": c.role, "parts": parts})

            json_to_save = {
                "request": serialized_request,
                "response": decision_json
            }
            
            self.create_json_file(json_to_save, file_prefix)
            return json_to_save

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode LLM JSON response: {e}")
            return None
        except Exception as e:
            logger.error(f"An error occurred while communicating with the LLM: {e}")
            return None

    def calculate_cost(self, model: str, usage, usd_to_inr: float = None):
        """
        Calculates cost based on Gemini Usage Metadata.
        """
        try:
            pricing = LLM_PRICING
            if not usd_to_inr:
                usd_to_inr = LLM_PRICING['usd_to_inr']['inr']

            # Logic to find model in pricing config
            model_base = next((m for m in pricing if model == m), None)
            if not model_base:
                for base_name in pricing:
                    if base_name in model:
                        model_base = base_name
                        break
                    
            input_rate = pricing.get(model_base, {}).get("input", 0)
            output_rate = pricing.get(model_base, {}).get("output", 0)
            # Gemini SDK Usage fields
            prompt_tokens = usage.prompt_token_count
            completion_tokens = usage.candidates_token_count
            thought_tokens = usage.thoughts_token_count if usage.thoughts_token_count else 0
            cached_tokens = usage.cached_content_token_count if usage.cached_content_token_count else 0

            billable_prompt = max(float(prompt_tokens - cached_tokens), 0.0)
            billable_completion = float(completion_tokens + thought_tokens)

            logger.info(f"Usage for model {model}: {usage}")
            logger.info(f"Prompt Tokens: {prompt_tokens}, Completion Tokens: {completion_tokens}, thought_tokens :{thought_tokens}")
            logger.info(f"Cached Tokens: {cached_tokens}")
            logger.info(f"Billable Prompt Tokens: {billable_prompt}, Billable Completion Tokens: {billable_completion}")

            # Cost computation
            cost_usd = (billable_prompt / 1000000.0) * input_rate + (billable_completion / 1000000.0) * output_rate
            cost_inr = cost_usd * usd_to_inr

            return {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "thought_tokens": thought_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd,
                "cost_inr": cost_inr,
            }
        except Exception as e:
            logger.error(f"Error calculating cost: {e}")
            return {}

    def create_json_file(self, body, prefix:str = "JSON"):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_prefix = re.sub(r'[\\/*?:"<>|]', "_", str(prefix))
            json_file_name = f"{timestamp}_{safe_prefix}.json"
            json_file_path = os.path.join(JSON_REQ_RES_DIR, json_file_name)
    
            with open(json_file_path, "w", encoding="utf-8") as json_file:
                json.dump(body, json_file, ensure_ascii=False, indent=2)
    
        except Exception as e:
            logger.error(f"Failed to create JSON Prompt file: {e}")

    def _generate_content_wrapper(self, model: str, contents: list, config: types.GenerateContentConfig):
        """
        Wrapper to make the actual API call with a retry mechanism.
        Retries up to 3 times on failure.
        """
        MAX_RETRIES = GEMINI_LLM_CONFIG.get('max_retries', 3)
        for attempt in range(MAX_RETRIES):
            try:
                start_time = datetime.now()
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.info(f"*******Gemini API Call Duration: {duration} seconds (Attempt {attempt + 1})*******")
                # If successful, return the response immediately
                return response
            
            # We catch exceptions, as the SDK raises them on errors.
            except Exception as e:
                # Log the error for the current attempt
                logger.warning(f"Gemini API Call Failed (Attempt {attempt + 1} of {MAX_RETRIES}): {e}")
                
                # If this was the last attempt, re-raise the exception
                if attempt + 1 == MAX_RETRIES:
                    logger.error(f"Gemini API Call failed after {MAX_RETRIES} attempts.")
                    raise e
                
                wait_time = 2  # Simple fixed wait time in seconds
                logger.info(f"Waiting for {wait_time} seconds before retrying...")
                time.sleep(wait_time)

if __name__ == "__main__":
    try:
        analyzer = GeminiLLMClient()
        analyzer.get_image_analysis_response(image_path="charts/RELIANCE_2025-12-07_21-01-00.png")
        print("Gemini Client Initialized Successfully")
    except Exception as e:
        print(f"Init failed: {e}")