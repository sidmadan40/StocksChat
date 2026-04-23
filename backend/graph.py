from typing import Any, Dict, List, TypedDict

from .utils import get_stock_data
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import MessageGraph


class GraphState(TypedDict):
    ticker: str
    query: str
    data: Dict[str, Any]
    market: Dict[str, Any]
    technical: Dict[str, Any]
    sentiment: Dict[str, Any]
    decision: Dict[str, Any]
    portfolio: Dict[str, Any]
    trace: List[Any]


def create_initial_state(ticker: str, query: str = "", portfolio: Dict[str, Any] | None = None) -> GraphState:
    return {
        'ticker': ticker,
        'query': query,
        'data': {},
        'market': {},
        'technical': {},
        'sentiment': {},
        'decision': {},
        'portfolio': portfolio or {'cash': 10000.0, 'positions': {}},
        'trace': []
    }


def fetch_data(state: GraphState) -> Dict[str, Any]:
    ticker = state['ticker']
    stock_data = get_stock_data(ticker)
    state['data'] = stock_data
    state['trace'].append({
        'step': 'fetch_data',
        'input': {'ticker': ticker},
        'output': {'latest_price': stock_data['latest_price'], 'pe_ratio': stock_data['pe_ratio']}
    })
    return {'data': stock_data, 'trace': state['trace']}


def market_node(state: GraphState) -> Dict[str, Any]:
    stock_data = state['data']
    hist = stock_data['historical_data']
    avg_price = hist['Close'].mean()
    latest = stock_data['latest_price']
    signal = 'bullish' if latest > avg_price else 'bearish'

    state['market'] = {'signal': signal}
    state['trace'].append({
        'step': 'market_node',
        'input': {'latest_price': latest, 'historical_average': avg_price},
        'output': {'signal': signal}
    })
    return {'market': state['market'], 'trace': state['trace']}


def technical_node(state: GraphState) -> Dict[str, Any]:
    stock_data = state['data']
    hist = stock_data['historical_data']
    if len(hist) < 50:
        signal = 'insufficient_data'
        ma50 = None
    else:
        ma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        latest = stock_data['latest_price']
        signal = 'bullish' if latest > ma50 else 'bearish'

    state['technical'] = {'signal': signal, 'ma50': ma50}
    state['trace'].append({
        'step': 'technical_node',
        'input': {'latest_price': stock_data['latest_price'], 'ma50': ma50},
        'output': {'signal': signal}
    })
    return {'technical': state['technical'], 'trace': state['trace']}


def sentiment_node(state: GraphState) -> Dict[str, Any]:
    signal = 'neutral'
    state['sentiment'] = {'signal': signal}
    state['trace'].append({
        'step': 'sentiment_node',
        'input': {'data_keys': list(state['data'].keys())},
        'output': {'signal': signal}
    })
    return {'sentiment': state['sentiment'], 'trace': state['trace']}


def decision_node(state: GraphState) -> Dict[str, Any]:
    market_signal = state['market'].get('signal')
    tech_signal = state['technical'].get('signal')
    sent_signal = state['sentiment'].get('signal')

    signals = [market_signal, tech_signal]
    bullish_count = signals.count('bullish')
    bearish_count = signals.count('bearish')

    if bullish_count == 2:
        decision = 'BUY'
        confidence = 0.8
    elif bearish_count == 2:
        decision = 'SELL'
        confidence = 0.8
    else:
        decision = 'HOLD'
        confidence = 0.5

    state['decision'] = {
        'decision': decision,
        'confidence': confidence,
        'signals': {
            'market': market_signal,
            'technical': tech_signal,
            'sentiment': sent_signal
        }
    }
    state['trace'].append({
        'step': 'decision_node',
        'input': {'market_signal': market_signal, 'technical_signal': tech_signal, 'sentiment_signal': sent_signal},
        'output': state['decision']
    })
    return {'decision': state['decision'], 'trace': state['trace']}


def query_router_node(state: GraphState) -> Dict[str, Any]:
    state['trace'].append({
        'step': 'query_router_node',
        'input': {'query': state.get('query', '')},
        'output': {'route': 'portfolio_node' if 'portfolio' in state.get('query', '').lower() else 'full_pipeline'}
    })
    return {'trace': state['trace']}


def portfolio_node(state: GraphState) -> Dict[str, Any]:
    state['trace'].append({
        'step': 'portfolio_node',
        'input': {'query': state.get('query', '')},
        'output': {'portfolio': state['portfolio']}
    })
    return {'portfolio': state['portfolio'], 'trace': state['trace']}


def execution_node(state: GraphState) -> Dict[str, Any]:
    current_price = state['data']['latest_price']
    portfolio = state['portfolio'] or {'cash': 10000.0, 'positions': {}}
    decision = state['decision']['decision']
    ticker = state['ticker']

    if decision == 'BUY' and current_price:
        invest_amount = portfolio['cash'] * 0.1
        shares = int(invest_amount // current_price)
        if shares > 0:
            portfolio['cash'] -= shares * current_price
            portfolio['positions'][ticker] = portfolio['positions'].get(ticker, 0) + shares
    elif decision == 'SELL' and ticker in portfolio['positions']:
        shares = portfolio['positions'].pop(ticker)
        portfolio['cash'] += shares * current_price

    state['portfolio'] = portfolio
    state['trace'].append({
        'step': 'execution_node',
        'input': {'decision': decision, 'ticker': ticker, 'price': current_price},
        'output': {'portfolio': portfolio}
    })
    return {'portfolio': portfolio, 'trace': state['trace']}


def build_stock_state_graph():
    graph = StateGraph(state_schema=GraphState)
    graph.add_node('query_router', query_router_node)
    graph.add_node('fetch_data', fetch_data)
    graph.add_node('market_node', market_node)
    graph.add_node('technical_node', technical_node)
    graph.add_node('sentiment_node', sentiment_node)
    graph.add_node('decision_node', decision_node)
    graph.add_node('execution_node', execution_node)
    graph.add_node('portfolio_node', portfolio_node)

    graph.set_entry_point('query_router')
    graph.add_conditional_edges(
        'query_router',
        lambda state: 'portfolio_node' if 'portfolio' in state.get('query', '').lower() else 'fetch_data'
    )

    # Run market, technical, and sentiment analysis in parallel after fetch_data
    graph.add_edge('fetch_data', 'market_node')
    graph.add_edge('fetch_data', 'technical_node')
    graph.add_edge('fetch_data', 'sentiment_node')

    # Join all analysis signals into the decision node
    graph.add_edge('market_node', 'decision_node')
    graph.add_edge('technical_node', 'decision_node')
    graph.add_edge('sentiment_node', 'decision_node')
    graph.add_edge('decision_node', 'execution_node')

    graph.set_finish_point('execution_node')
    graph.set_finish_point('portfolio_node')

    return graph.compile()


def export_stock_state_graph_dot(compiled_graph=None) -> str:
    """Return a DOT format string for the compiled LangGraph state graph."""
    if compiled_graph is None:
        compiled_graph = build_stock_state_graph()

    graph = compiled_graph.get_graph()
    lines = ["digraph StockStateGraph {", "  rankdir=LR;"]

    for node_id, node in graph.nodes.items():
        label = node.name or node_id
        lines.append(f'  "{node_id}" [label="{label}", shape="box"];')

    for edge in graph.edges:
        lines.append(f'  "{edge.source}" -> "{edge.target}";')

    lines.append("}")
    return "\n".join(lines)


def export_stock_state_graph_networkx(compiled_graph=None):
    """Build a networkx DiGraph for the compiled LangGraph state graph."""
    try:
        import networkx as nx
    except ImportError as exc:
        raise ImportError("networkx is required to export the graph as a NetworkX object") from exc

    if compiled_graph is None:
        compiled_graph = build_stock_state_graph()

    graph = compiled_graph.get_graph()
    nx_graph = nx.DiGraph()

    for node_id, node in graph.nodes.items():
        nx_graph.add_node(node_id, label=node.name or node_id)

    for edge in graph.edges:
        nx_graph.add_edge(edge.source, edge.target)

    return nx_graph


def export_stock_state_graph_graphviz(compiled_graph=None):
    """Build a graphviz Digraph for the compiled LangGraph state graph."""
    try:
        from graphviz import Digraph
    except ImportError as exc:
        raise ImportError("graphviz is required to export the graph as a Graphviz Digraph") from exc

    if compiled_graph is None:
        compiled_graph = build_stock_state_graph()

    graph = compiled_graph.get_graph()
    dot = Digraph(name="StockStateGraph")
    dot.attr(rankdir="LR")

    for node_id, node in graph.nodes.items():
        dot.node(node_id, label=node.name or node_id, shape="box")

    for edge in graph.edges:
        dot.edge(edge.source, edge.target)

    return dot


def build_query_routing_graph():
    """Build a simple routing graph for stock-related user queries."""
    graph = MessageGraph()

    def detect_intent(state):
        prompt = state[-1].content if state else ""
        prompt_lower = prompt.lower()

        if "correlation" in prompt_lower:
            intent = "correlation"
        elif "portfolio" in prompt_lower:
            intent = "portfolio"
        elif "pnl" in prompt_lower or "pl" in prompt_lower or "profit" in prompt_lower or "loss" in prompt_lower:
            intent = "pnl"
        else:
            intent = "analyze"

        return [AIMessage(content=intent)]

    graph.add_node("intent_detector", detect_intent)
    graph.set_entry_point("intent_detector")
    graph.set_finish_point("intent_detector")
    return graph


def route_query(prompt: str) -> str:
    """Route a free-text query to a high-level intent."""
    graph = build_query_routing_graph().compile()
    result = graph.invoke([HumanMessage(content=prompt)])
    if result and len(result) > 0:
        return result[0].content
    return "analyze"
