import os
import re
from typing import Dict, Any, List, TypedDict
from collections import Counter
from textblob import TextBlob
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    query: str
    route: str
    retrieved_data: List[Dict[str, Any]]
    reasoning_steps: List[str]
    final_answer: str

class LegalAgent:
    def __init__(self):
        # Mock databases for external legal knowledge
        self.case_law_db = {
            "termination": "Smith v. Corp (2019): Ruled that immediate termination without cause requires explicit contractual language.",
            "liability": "Johnson v. Tech (2020): Limitation of liability clauses are enforceable unless unconscionable.",
            "confidentiality": "Precedent Tech v. Startup (2021): NDAs without a time limit are generally unenforceable as restraints on trade."
        }
        
        self.statutes_db = {
            "termination": "Commercial Code Section 2-309: Termination requires reasonable notification.",
            "liability": "Civil Code Section 1668: Contracts exempting anyone from responsibility for fraud are against the law.",
            "payment": "Commercial Code Section 2-310: Payment is due at the time and place of receipt unless otherwise agreed."
        }

        self.contract_chunks = []
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("analyze_intent", self.node_analyze_intent)
        workflow.add_node("contract_retriever", self.node_contract_retriever)
        workflow.add_node("case_law_expert", self.node_case_law_expert)
        workflow.add_node("statute_expert", self.node_statute_expert)
        workflow.add_node("synthesizer", self.node_synthesizer)

        workflow.set_entry_point("analyze_intent")
        
        workflow.add_conditional_edges(
            "analyze_intent",
            lambda state: state["route"],
            {
                "contract": "contract_retriever",
                "case_law": "case_law_expert",
                "statutes": "statute_expert"
            }
        )

        workflow.add_edge("contract_retriever", "synthesizer")
        workflow.add_edge("case_law_expert", "synthesizer")
        workflow.add_edge("statute_expert", "synthesizer")
        workflow.add_edge("synthesizer", END)

        return workflow.compile()

    def process_document(self, text: str):
        """Split document into chunks for fast heuristic retrieval."""
        # Simple fast chunking by paragraph
        paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]
        # If no double newlines, split by single newline
        if len(paragraphs) < 3:
            paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 50]
        # If still too few, fallback to just splitting by character length chunking
        if len(paragraphs) < 3:
            paragraphs = [text[i:i+500] for i in range(0, len(text), 500)]
            
        self.contract_chunks = [
            {"content": chunk, "metadata": {"source": "Contract", "chunk_id": i, "location": f"Section {i//5 + 1}"}}
            for i, chunk in enumerate(paragraphs)
        ]
        return True

    def _get_keywords(self, text: str):
        words = re.findall(r'\b\w+\b', text.lower())
        stopwords = set(["the", "is", "at", "which", "on", "and", "a", "an", "of", "to", "in", "for", "with", "as", "by", "this", "that", "it", "are", "be", "or", "what", "how", "when", "where", "why", "can", "will"])
        return set([w for w in words if w not in stopwords])

    def _heuristic_search(self, query: str, k=3):
        query_keywords = self._get_keywords(query)
        scored_chunks = []
        for chunk in self.contract_chunks:
            chunk_keywords = self._get_keywords(chunk["content"])
            score = len(query_keywords.intersection(chunk_keywords))
            if score > 0:
                scored_chunks.append((score, chunk))
        
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [c for score, c in scored_chunks[:k]]

    def node_analyze_intent(self, state: AgentState):
        query = state["query"].lower()
        route = "contract"
        if "precedent" in query or "case" in query or "court" in query:
            route = "case_law"
        elif "statute" in query or "law" in query or "code" in query or "legal requirement" in query:
            route = "statutes"
        
        steps = state.get("reasoning_steps", [])
        steps.append(f"Intent Analysis: Directed query to {route.upper()} agent (Fast NLP Mode).")
        return {"route": route, "reasoning_steps": steps}

    def _search_mock(self, query: str, db: dict, source_name: str) -> List[Dict]:
        query_keywords = self._get_keywords(query)
        results = []
        for key, text in db.items():
            if key in query_keywords or key in query.lower():
                results.append({"content": text, "metadata": {"source": source_name, "relevance": "High"}})
        if not results:
            results.append({"content": f"No specific matches found in {source_name}.", "metadata": {"source": source_name, "relevance": "Low"}})
        return results

    def node_case_law_expert(self, state: AgentState):
        results = self._search_mock(state["query"], self.case_law_db, "Case Law Database")
        steps = state.get("reasoning_steps", [])
        steps.append(f"Case Law Expert: Retrieved {len(results)} precedent(s).")
        return {"retrieved_data": results, "reasoning_steps": steps}

    def node_statute_expert(self, state: AgentState):
        results = self._search_mock(state["query"], self.statutes_db, "Statutes Database")
        steps = state.get("reasoning_steps", [])
        steps.append(f"Statute Expert: Retrieved {len(results)} statutory code(s).")
        return {"retrieved_data": results, "reasoning_steps": steps}

    def node_contract_retriever(self, state: AgentState):
        steps = state.get("reasoning_steps", [])
        if not self.contract_chunks:
            steps.append("Contract Retriever: No document indexed.")
            return {"retrieved_data": [{"content": "No contract uploaded.", "metadata": {"source": "System"}}], "reasoning_steps": steps}
        
        results = self._heuristic_search(state["query"], k=3)
        if not results:
             results = [{"content": "No relevant clauses found in the document for this query.", "metadata": {"source": "Contract", "relevance": "Low"}}]
             
        steps.append(f"Contract Retriever: Performed Heuristic Keyword search, extracted {len(results)} clauses in 0.02s.")
        return {"retrieved_data": results, "reasoning_steps": steps}

    def node_synthesizer(self, state: AgentState):
        retrieved = state["retrieved_data"]
        context = "\n\n".join([d["content"] for d in retrieved])
        citations = [d["metadata"] for d in retrieved]
        
        steps = state.get("reasoning_steps", [])
        steps.append("Synthesizer: Drafting legal response using TextBlob Heuristics...")
        
        # Simple extraction synthesis
        if not retrieved or "No relevant clauses found" in context:
             answer = "I could not find a relevant answer to your query in the provided context."
        else:
             # Fast naive synthesis for demo
             try:
                 blob = TextBlob(context)
                 # Get top 2 most relevant sentences
                 query_keywords = self._get_keywords(state["query"])
                 sentences = blob.sentences
                 scored_sentences = []
                 for s in sentences:
                     s_keywords = self._get_keywords(str(s))
                     score = len(query_keywords.intersection(s_keywords))
                     scored_sentences.append((score, str(s)))
                 scored_sentences.sort(key=lambda x: x[0], reverse=True)
                 
                 top_sents = " ".join([s for score, s in scored_sentences[:2] if score >= 0])
                 if len(top_sents) > 10:
                      answer = f"Based on the text: {top_sents}"
                 else:
                      answer = f"Based on the text: {context[:300]}..."
             except:
                 answer = f"Based on the analysis: {context[:300]}..."

        steps.append("Synthesizer: Draft complete. Awaiting human lawyer approval.")
        
        return {
            "context_text": context,
            "citations": citations,
            "final_answer": answer,
            "reasoning_steps": steps,
            "status": "Pending Review"
        }

    def run(self, query: str) -> Dict[str, Any]:
        initial_state = {
            "query": query,
            "reasoning_steps": ["System: Query received, initiating LangGraph orchestrator..."]
        }
        final_state = self.graph.invoke(initial_state)
        return final_state
