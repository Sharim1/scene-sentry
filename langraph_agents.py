"""
LangGraph-based Entertainment Discovery Agent System

This module implements a sophisticated multi-agent system using LangGraph for 
intelligent entertainment content discovery and recommendation.
"""

import os
import json
import logging
from typing import Dict, List, TypedDict, Literal, Optional, Any
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from tavily import TavilyClient
from langchain_core.tools import tool

from app import db
from models import User, Content, Recommendation, SearchLog
from content_apis import TMDbAPI


class AgentState(TypedDict):
    """State object that flows through the LangGraph workflow"""
    user_id: int
    user_preferences: Dict[str, Any]
    search_query: Optional[str]
    search_results: List[Dict[str, Any]]
    analyzed_content: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    messages: List[BaseMessage]
    step_count: int
    max_steps: int
    error_count: int
    current_node: str


class EntertainmentDiscoveryGraph:
    """
    LangGraph-based entertainment discovery system with multiple specialized agents
    """
    
    def __init__(self):
        self.llm = self._initialize_llm()
        self.tavily = self._initialize_tavily()
        self.tmdb = TMDbAPI()
        self.memory = MemorySaver()
        self.graph = self._create_graph()
        
    def _initialize_llm(self):
        """Initialize the Google Gemini LLM"""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",
            google_api_key=api_key,
            temperature=0.7,
            max_output_tokens=2048,
        )
    
    def _initialize_tavily(self):
        """Initialize Tavily search client"""
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logging.warning("TAVILY_API_KEY not found, search functionality will be limited")
            return None
        
        return TavilyClient(api_key=api_key)
    
    def _create_graph(self):
        """Create the LangGraph workflow"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("preference_analyzer", self.analyze_preferences)
        workflow.add_node("search_planner", self.plan_searches)
        workflow.add_node("content_searcher", self.search_content)
        workflow.add_node("content_analyzer", self.analyze_content)
        workflow.add_node("recommendation_generator", self.generate_recommendations)
        workflow.add_node("quality_validator", self.validate_quality)
        
        # Define the workflow path
        workflow.set_entry_point("preference_analyzer")
        
        workflow.add_edge("preference_analyzer", "search_planner")
        workflow.add_edge("search_planner", "content_searcher")
        workflow.add_edge("content_searcher", "content_analyzer")
        workflow.add_edge("content_analyzer", "recommendation_generator")
        workflow.add_edge("recommendation_generator", "quality_validator")
        
        # Add conditional routing from quality_validator
        workflow.add_conditional_edges(
            "quality_validator",
            self.should_continue,
            {
                "continue": "search_planner",  # Search for more content
                "finish": END,  # End workflow
                "retry": "content_analyzer"  # Retry analysis
            }
        )
        
        return workflow.compile(checkpointer=self.memory)
    
    async def analyze_preferences(self, state: AgentState) -> AgentState:
        """Analyze user preferences and viewing history"""
        logging.info(f"[{state['current_node']}] Starting preference analysis")
        
        try:
            user = User.query.get(state["user_id"])
            if not user:
                raise ValueError(f"User {state['user_id']} not found")
            
            # Gather user data
            library_items = user.library_items
            preferred_genres = []
            if user.preferred_genres:
                try:
                    preferred_genres = json.loads(user.preferred_genres)
                except:
                    pass
            
            # Build context about user's preferences
            preference_data = {
                "explicit_genres": preferred_genres,
                "library_size": len(library_items),
                "highly_rated": [],
                "content_types": [],
                "recent_activity": []
            }
            
            # Analyze library for implicit preferences
            for item in library_items[-10:]:  # Recent items
                if item.status in ['confirmed', 'in_progress', 'finished']:
                    content = item.content
                    preference_data["content_types"].append(content.content_type)
                    
                    if item.rating and item.rating >= 4:
                        preference_data["highly_rated"].append({
                            "title": content.title,
                            "type": content.content_type,
                            "genres": content.genres,
                            "rating": item.rating
                        })
            
            # Use LLM to analyze preferences deeply
            analysis_prompt = f"""
            Analyze this user's entertainment preferences and create a detailed profile:
            
            User Data: {json.dumps(preference_data, indent=2)}
            
            Please provide a comprehensive analysis including:
            1. Genre preferences (both explicit and inferred)
            2. Content type preferences (movies vs TV vs books)
            3. Themes and patterns in their choices
            4. Potential new genres they might enjoy
            5. Search strategies that would work best for this user
            
            Respond with a structured analysis that can guide content discovery.
            """
            
            messages = [HumanMessage(content=analysis_prompt)]
            response = await self.llm.ainvoke(messages)
            
            state["user_preferences"] = {
                "raw_data": preference_data,
                "analysis": response.content,
                "explicit_genres": preferred_genres,
                "discovery_frequency": user.discovery_frequency or 30
            }
            
            state["messages"].append(HumanMessage(content=analysis_prompt))
            state["messages"].append(response)
            state["step_count"] += 1
            state["current_node"] = "preference_analyzer"
            
            logging.info(f"[preference_analyzer] Analysis completed for user {user.username}")
            
        except Exception as e:
            logging.error(f"[preference_analyzer] Error: {e}")
            state["error_count"] += 1
            state["user_preferences"] = {
                "raw_data": {},
                "analysis": f"Error analyzing preferences: {str(e)}",
                "explicit_genres": [],
                "discovery_frequency": 30
            }
        
        return state
    
    async def plan_searches(self, state: AgentState) -> AgentState:
        """Plan intelligent search queries based on user preferences"""
        logging.info(f"[{state['current_node']}] Planning search strategies")
        
        try:
            preferences = state["user_preferences"]
            
            planning_prompt = f"""
            Based on this user's preferences, create 3-5 strategic search queries for discovering new entertainment content:
            
            User Analysis: {preferences.get('analysis', 'No analysis available')}
            Explicit Genres: {preferences.get('explicit_genres', [])}
            
            Create search queries that:
            1. Explore their known preferences more deeply
            2. Introduce adjacent genres they might enjoy
            3. Find hidden gems and recent releases
            4. Include different content types (movies, TV, books)
            
            Format as a JSON list of search query strings.
            Example: ["best sci-fi movies 2024 reviews", "psychological thriller books recommendations"]
            """
            
            messages = [HumanMessage(content=planning_prompt)]
            response = await self.llm.ainvoke(messages)
            
            # Parse the response to extract search queries
            try:
                # Try to extract JSON from the response
                content = response.content
                if "```json" in content:
                    json_start = content.find("```json") + 7
                    json_end = content.find("```", json_start)
                    json_str = content[json_start:json_end].strip()
                else:
                    json_str = content.strip()
                
                search_queries = json.loads(json_str)
                if not isinstance(search_queries, list):
                    raise ValueError("Response is not a list")
                    
            except Exception as e:
                logging.warning(f"Could not parse search queries JSON: {e}")
                # Fallback to default queries based on preferences
                explicit_genres = preferences.get('explicit_genres', [])
                search_queries = []
                for genre in explicit_genres[:3]:
                    search_queries.append(f"best {genre.lower()} movies 2024")
                    search_queries.append(f"{genre.lower()} TV shows recommendations")
                
                if not search_queries:
                    search_queries = [
                        "best movies 2024 reviews",
                        "popular TV shows streaming",
                        "must read books 2024"
                    ]
            
            state["search_query"] = search_queries[0]  # Start with first query
            state["remaining_queries"] = search_queries[1:]  # Store rest for later
            
            state["messages"].append(HumanMessage(content=planning_prompt))
            state["messages"].append(response)
            state["step_count"] += 1
            state["current_node"] = "search_planner"
            
            logging.info(f"[search_planner] Planned {len(search_queries)} search queries")
            
        except Exception as e:
            logging.error(f"[search_planner] Error: {e}")
            state["error_count"] += 1
            state["search_query"] = "best movies 2024 reviews"
            state["remaining_queries"] = []
        
        return state
    
    async def search_content(self, state: AgentState) -> AgentState:
        """Search for content using Tavily"""
        logging.info(f"[{state['current_node']}] Searching with query: {state['search_query']}")
        
        try:
            if not self.tavily:
                # Fallback when Tavily is not available
                state["search_results"] = [{
                    "title": "Tavily Search Unavailable",
                    "content": "Search functionality is currently limited. Using fallback recommendations.",
                    "url": ""
                }]
            else:
                # Perform Tavily search
                query = state["search_query"]
                response = self.tavily.search(query=query, max_results=8, search_depth="advanced")
                search_results = response.get("results", [])
                
                # Process and structure the results
                processed_results = []
                for result in search_results:
                    processed_results.append({
                        "title": result.get("title", ""),
                        "content": result.get("content", ""),
                        "url": result.get("url", ""),
                        "query": query
                    })
                
                state["search_results"] = processed_results
                
                # Log the search
                search_log = SearchLog(
                    user_id=state["user_id"],
                    query=query,
                    results_count=len(processed_results),
                    api_used='tavily'
                )
                db.session.add(search_log)
                db.session.commit()
            
            state["step_count"] += 1
            state["current_node"] = "content_searcher"
            
            logging.info(f"[content_searcher] Found {len(state['search_results'])} results")
            
        except Exception as e:
            logging.error(f"[content_searcher] Error: {e}")
            state["error_count"] += 1
            state["search_results"] = [{
                "title": f"Search Error: {str(e)}",
                "content": "An error occurred during search. Using fallback content.",
                "url": ""
            }]
        
        return state
    
    async def analyze_content(self, state: AgentState) -> AgentState:
        """Analyze search results to extract entertainment content"""
        logging.info(f"[{state['current_node']}] Analyzing {len(state['search_results'])} search results")
        
        try:
            search_results = state["search_results"]
            user_preferences = state["user_preferences"]
            
            # Limit analysis to top 5 results for speed
            limited_results = search_results[:5]
            
            # Batch process all results in a single prompt for efficiency
            batch_prompt = f"""
            Analyze these search results to extract entertainment content information:
            
            User Preferences: {user_preferences.get('explicit_genres', [])}
            
            Search Results:
            {chr(10).join([f"Result {i+1}: {result['title']} - {result['content'][:400]}" for i, result in enumerate(limited_results)])}
            
            Extract any movies, TV shows, or books mentioned across ALL results. For each item found, provide:
            1. Title
            2. Content type (movie, tv_show, or book)  
            3. Genre(s)
            4. Release year (if available)
            5. Brief description
            6. Confidence score (0-1) based on preference matching
            
            Format as JSON array of objects. Limit to top 10 most relevant items.
            """
            
            try:
                messages = [HumanMessage(content=batch_prompt)]
                response = await self.llm.ainvoke(messages)
                
                # Parse the response
                content = response.content
                if "```json" in content:
                    json_start = content.find("```json") + 7
                    json_end = content.find("```", json_start)
                    json_str = content[json_start:json_end].strip()
                else:
                    json_str = content.strip()
                
                analyzed_content = json.loads(json_str)
                if not isinstance(analyzed_content, list):
                    analyzed_content = []
                    
            except Exception as e:
                logging.warning(f"Could not analyze results: {e}")
                analyzed_content = []
            
            state["analyzed_content"] = analyzed_content
            state["step_count"] += 1
            state["current_node"] = "content_analyzer"
            
            logging.info(f"[content_analyzer] Analyzed and found {len(analyzed_content)} content items")
            
        except Exception as e:
            logging.error(f"[content_analyzer] Error: {e}")
            state["error_count"] += 1
            state["analyzed_content"] = []
        
        return state
    
    async def generate_recommendations(self, state: AgentState) -> AgentState:
        """Generate final recommendations with reasoning"""
        logging.info(f"[{state['current_node']}] Generating recommendations from {len(state['analyzed_content'])} items")
        
        try:
            analyzed_content = state["analyzed_content"]
            user_preferences = state["user_preferences"]
            user = User.query.get(state["user_id"])
            
            recommendations = []
            seen_titles = set()  # Track titles to prevent duplicates
            
            # Get existing recommendations to avoid duplicates
            existing_recs = db.session.query(Recommendation).join(Content).filter(
                Recommendation.user_id == state["user_id"],
                Recommendation.dismissed == False
            ).all()
            existing_titles = {rec.content.title.lower().strip() for rec in existing_recs}
            
            for item in analyzed_content:
                try:
                    # Get or create content in database
                    title = item.get('title', '').strip()
                    content_type = item.get('content_type', '').strip()
                    
                    if not title or not content_type:
                        continue
                    
                    # Skip if we've already seen this title (prevent duplicates)
                    title_lower = title.lower().strip()
                    if title_lower in seen_titles or title_lower in existing_titles:
                        continue
                    seen_titles.add(title_lower)
                    
                    # Check if content already exists
                    existing_content = Content.query.filter_by(
                        title=title,
                        content_type=content_type
                    ).first()
                    
                    if not existing_content:
                        # Create new content record
                        content_record = Content(
                            title=title,
                            content_type=content_type,
                            description=item.get('description', ''),
                            genres=json.dumps(item.get('genres', [])),
                            release_date=str(item.get('release_year', '')),
                        )
                        
                        # Enhance with TMDb data if available
                        if content_type in ['movie', 'tv_show']:
                            tmdb_data = self.tmdb.search_content(title, content_type)
                            if tmdb_data:
                                content_record.tmdb_id = tmdb_data.get('id')
                                content_record.poster_url = tmdb_data.get('poster_path')
                                content_record.rating = tmdb_data.get('vote_average')
                                if tmdb_data.get('overview'):
                                    content_record.description = tmdb_data.get('overview')
                        
                        db.session.add(content_record)
                        db.session.commit()
                        content_record_id = content_record.id
                    else:
                        content_record_id = existing_content.id
                    
                    # Create recommendation
                    confidence_score = float(item.get('confidence_score', 0.7))
                    reasoning = item.get('reasoning', 'Recommended based on your preferences')
                    
                    recommendation = Recommendation(
                        user_id=state["user_id"],
                        content_id=content_record_id,
                        confidence_score=confidence_score,
                        reasoning=reasoning,
                        source_urls=json.dumps([])
                    )
                    
                    db.session.add(recommendation)
                    recommendations.append({
                        'content_id': content_record_id,
                        'title': title,
                        'content_type': content_type,
                        'confidence_score': confidence_score,
                        'reasoning': reasoning
                    })
                    
                except Exception as e:
                    logging.warning(f"Could not create recommendation for {item}: {e}")
                    continue
            
            db.session.commit()
            
            state["recommendations"] = recommendations
            state["step_count"] += 1
            state["current_node"] = "recommendation_generator"
            
            logging.info(f"[recommendation_generator] Generated {len(recommendations)} recommendations")
            
        except Exception as e:
            logging.error(f"[recommendation_generator] Error: {e}")
            state["error_count"] += 1
            state["recommendations"] = []
        
        return state
    
    async def validate_quality(self, state: AgentState) -> AgentState:
        """Validate the quality of recommendations and decide next steps"""
        logging.info(f"[{state['current_node']}] Validating {len(state['recommendations'])} recommendations")
        
        try:
            recommendations = state["recommendations"]
            
            # Quality metrics
            quality_score = 0.0
            total_confidence = sum(r['confidence_score'] for r in recommendations)
            avg_confidence = total_confidence / len(recommendations) if recommendations else 0
            
            # Evaluate quality
            quality_checks = {
                "has_recommendations": len(recommendations) > 0,
                "sufficient_count": len(recommendations) >= 2,
                "good_confidence": avg_confidence >= 0.6,
                "diverse_types": len(set(r['content_type'] for r in recommendations)) > 1,
                "not_too_many_errors": state["error_count"] < 3
            }
            
            quality_score = sum(quality_checks.values()) / len(quality_checks)
            
            state["quality_score"] = quality_score
            state["quality_checks"] = quality_checks
            state["step_count"] += 1
            state["current_node"] = "quality_validator"
            
            logging.info(f"[quality_validator] Quality score: {quality_score:.2f}")
            
        except Exception as e:
            logging.error(f"[quality_validator] Error: {e}")
            state["error_count"] += 1
            state["quality_score"] = 0.0
            state["quality_checks"] = {}
        
        return state
    
    def should_continue(self, state: AgentState) -> Literal["continue", "finish", "retry"]:
        """Determine whether to continue, finish, or retry"""
        
        quality_score = state.get("quality_score", 0.0)
        step_count = state.get("step_count", 0)
        max_steps = state.get("max_steps", 8)  # Reduced max steps for speed
        error_count = state.get("error_count", 0)
        recommendations_count = len(state.get("recommendations", []))
        
        # Always finish if we have good results - don't loop back
        if quality_score >= 0.8 and recommendations_count >= 5:
            return "finish"
            
        # Finish if we have reasonable results and not too many steps
        if recommendations_count >= 3 and step_count >= 6:
            return "finish"
        
        # Too many steps or errors - always finish
        if step_count >= max_steps or error_count >= 3:
            return "finish"
        
        # For speed, finish after first successful batch
        if recommendations_count >= 2 and quality_score >= 0.6:
            return "finish"
        
        return "finish"  # Default to finish for speed
    
    async def run_discovery(self, user_id: int, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Run the complete discovery workflow for a user"""
        
        # Initialize state
        initial_state = AgentState(
            user_id=user_id,
            user_preferences={},
            search_query=search_query,
            search_results=[],
            analyzed_content=[],
            recommendations=[],
            messages=[],
            step_count=0,
            max_steps=15,
            error_count=0,
            current_node="start",
            remaining_queries=[]
        )
        
        # Run the graph
        thread_id = f"user_{user_id}_{datetime.now().isoformat()}"
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            # Execute the workflow
            final_state = await self.graph.ainvoke(initial_state, config=config)
            
            logging.info(f"Discovery completed for user {user_id}: "
                        f"{len(final_state['recommendations'])} recommendations, "
                        f"quality score: {final_state.get('quality_score', 0):.2f}")
            
            return final_state["recommendations"]
            
        except Exception as e:
            logging.error(f"Discovery workflow failed for user {user_id}: {e}")
            return []


# Global instance
discovery_graph = EntertainmentDiscoveryGraph()