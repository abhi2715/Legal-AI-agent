import os
import torch
from typing import Dict, Any, List, TypedDict

torch.set_num_threads(1)

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from langgraph.graph import StateGraph, END

# Define the State for LangGraph
class AgentState(TypedDict):
    query: str
    route: str
    retrieved_data: List[Dict]
    context_text: str
    citations: List[Dict]
    reasoning_steps: List[str]
    final_answer: str
    status: str

class LegalAgent:
    def __init__(self):
        # Initialize models
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.tokenizer = AutoTokenizer.from_pretrained("google/flan-t5-small")
        self.model = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-small")
        
        self.contract_vector_store = None
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
        )
        
        # Enterprise Mock Databases
        self.case_law_db = {
            "termination": "Precedent Smith v. Corp (2020) [Citation: 134 F.3d 29]: Termination clauses must provide at least 30 days notice to be enforceable under standard commercial law. Implied covenant of good faith applies.",
            "liability": "Precedent Doe v. Enterprises (2018) [Citation: 99 U.S. 112]: Established that caps on liability cannot exclude gross negligence or willful misconduct, regardless of contract wording.",
            "confidentiality": "Precedent Tech v. Startup (2021) [Citation: 45 Del. Ch. 11]: Ruled that NDAs without a specific time limit are generally unenforceable as unreasonable restraints on trade."
        }
        
        self.statutes_db = {
            "termination": "Commercial Code Section 2-309: Termination of a contract requires reasonable notification. An agreement dispensing with notification is invalid if its operation would be unconscionable.",
            "liability": "Civil Code Section 1668: Contracts that exempt anyone from responsibility for their own fraud or willful injury to the person or property of another are against the policy of the law.",
            "payment": "Commercial Code Section 2-310: Payment is due at the time and place at which the buyer is to receive the goods, unless otherwise agreed."
        }

        # Build the LangGraph
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        # Add Nodes
        workflow.add_node("analyze_intent", self.node_analyze_intent)
        workflow.add_node("contract_retriever", self.node_contract_retriever)
        workflow.add_node("case_law_expert", self.node_case_law_expert)
        workflow.add_node("statute_expert", self.node_statute_expert)
        workflow.add_node("synthesizer", self.node_synthesizer)

        # Add Edges
        workflow.set_entry_point("analyze_intent")
        
        # Conditional routing from analyze_intent
        workflow.add_conditional_edges(
            "analyze_intent",
            lambda state: state["route"],
            {
                "contract": "contract_retriever",
                "case_law": "case_law_expert",
                "statutes": "statute_expert"
            }
        )

        # All experts go to synthesizer
        workflow.add_edge("contract_retriever", "synthesizer")
        workflow.add_edge("case_law_expert", "synthesizer")
        workflow.add_edge("statute_expert", "synthesizer")
        
        # End
        workflow.add_edge("synthesizer", END)

        return workflow.compile()

    def process_document(self, text: str):
        """Chunk and embed the uploaded contract."""
        chunks = self.text_splitter.split_text(text)
        docs = [
            Document(page_content=chunk, metadata={"source": "Contract", "chunk_id": i, "location": f"Section {i//5 + 1}"})
            for i, chunk in enumerate(chunks)
        ]
        self.contract_vector_store = FAISS.from_documents(docs, self.embeddings)
        return True

    # --- LANGGRAPH NODES ---

    def node_analyze_intent(self, state: AgentState):
        query = state["query"].lower()
        route = "contract"
        if "precedent" in query or "case" in query or "court" in query:
            route = "case_law"
        elif "statute" in query or "law" in query or "code" in query or "legal requirement" in query:
            route = "statutes"
        
        steps = state.get("reasoning_steps", [])
        steps.append(f"Intent Analysis: Directed query to {route.upper()} agent.")
        return {"route": route, "reasoning_steps": steps}

    def _search_mock(self, query: str, db: dict, source_name: str) -> List[Dict]:
        q = query.lower()
        results = []
        for key, text in db.items():
            if key in q:
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
        if not self.contract_vector_store:
            steps.append("Contract Retriever: No document indexed.")
            return {"retrieved_data": [{"content": "No contract uploaded.", "metadata": {"source": "System"}}], "reasoning_steps": steps}
        
        docs = self.contract_vector_store.similarity_search(state["query"], k=3)
        results = [{"content": doc.page_content, "metadata": doc.metadata} for doc in docs]
        steps.append(f"Contract Retriever: Performed FAISS vector search, extracted {len(results)} chunks.")
        return {"retrieved_data": results, "reasoning_steps": steps}

    def node_synthesizer(self, state: AgentState):
        retrieved = state["retrieved_data"]
        context = "\n\n".join([d["content"] for d in retrieved])
        citations = [d["metadata"] for d in retrieved]
        
        steps = state.get("reasoning_steps", [])
        steps.append("Synthesizer: Drafting legal response using Flan-T5 generative model...")
        
        prompt = f"Answer the legal query based ONLY on the provided context.\n\nContext:\n{context}\n\nQuery: {state['query']}\n\nAnswer:"
        
        try:
            inputs = self.tokenizer(prompt, return_tensors="pt", max_length=512, truncation=True)
            with torch.no_grad():
                outputs = self.model.generate(**inputs, max_length=200)
            answer = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            if len(answer) < 10 and context:
                answer = f"Based on the analysis: {context[:300]}..."
        except Exception as e:
            answer = f"Error during generation: {str(e)}"

        steps.append("Synthesizer: Draft complete. Awaiting human lawyer approval.")
        
        return {
            "context_text": context,
            "citations": citations,
            "final_answer": answer,
            "reasoning_steps": steps,
            "status": "Pending Review"
        }

    def run(self, query: str) -> Dict[str, Any]:
        """Invoke the LangGraph."""
        initial_state = {
            "query": query,
            "reasoning_steps": ["System: Query received, initiating LangGraph orchestrator..."]
        }
        
        final_state = self.graph.invoke(initial_state)
        
        return {
            "answer": final_state["final_answer"],
            "citations": final_state["citations"],
            "reasoning_steps": final_state["reasoning_steps"],
            "status": final_state["status"],
            "source": final_state["route"].upper()
        }
