"""Convert available OpenCode evidence into EvalScope's standard agent trace."""

from evalscope.api.agent import AgentTrace, AgentTraceEvent, EventType
from evalscope.api.messages import ChatMessage, ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from evalscope.api.tool.tool_call import ToolCall, ToolFunction

from .contracts import ExecutionResult


def session_messages(session: dict) -> list[ChatMessage] | None:
    """Expose tool calls and observations using the existing review conversation UI."""
    messages: list[ChatMessage] = []
    for message in session.get('messages', []):
        info, parts = message['info'], message.get('parts', [])
        text = '\n'.join(p.get('text', '') for p in parts if p['type'] == 'text')
        if info['role'] == 'user':
            messages.append(ChatMessageUser(id=info['id'], content=text))
            continue
        calls = [
            ToolCall(id=p['callID'], function=ToolFunction(name=p['tool'], arguments=p['state'].get('input', {})))
            for p in parts
            if p['type'] == 'tool'
        ]
        messages.append(
            ChatMessageAssistant(id=info['id'], content=text, tool_calls=calls or None, model=info.get('modelID'))
        )
        for part in parts:
            if part['type'] == 'tool' and part['state']['status'] in {'completed', 'error'}:
                state = part['state']
                messages.append(
                    ChatMessageTool(
                        id=part['id'],
                        tool_call_id=part['callID'],
                        function=part['tool'],
                        content=str(state.get('output', state.get('error', '')))[:8000],
                    )
                )
    return messages or None


def session_trace(session: dict, execution: ExecutionResult) -> AgentTrace:
    """Preserve observed timestamps and tool events; do not synthesize model internals."""
    trace = AgentTrace(framework='opencode', environment='local', trial_id=execution.attempt_id)
    for step, message in enumerate(session.get('messages', [])):
        info = message['info']
        if info.get('role') != 'assistant':
            continue
        timestamp = info.get('time', {}).get('created', 0) / 1000
        text = '\n'.join(p.get('text', '') for p in message.get('parts', []) if p['type'] == 'text')
        trace.events.append(
            AgentTraceEvent(
                step=step,
                timestamp=timestamp,
                type=EventType.MODEL_GENERATE,
                message_id=info['id'],
                payload={'text': text, 'model': info.get('modelID'), 'finish': info.get('finish')},
            )
        )
        for part in message.get('parts', []):
            if part['type'] != 'tool':
                continue
            state = part['state']
            trace.events.append(
                AgentTraceEvent(
                    step=step,
                    timestamp=state.get('time', {}).get('start', timestamp * 1000) / 1000,
                    type=EventType.TOOL_CALL,
                    message_id=info['id'],
                    payload={'name': part['tool'], 'arguments': state.get('input'), 'id': part.get('callID')},
                )
            )
            if state['status'] in {'completed', 'error'}:
                trace.events.append(
                    AgentTraceEvent(
                        step=step,
                        timestamp=state.get('time', {}).get('end', timestamp * 1000) / 1000,
                        type=EventType.TOOL_RESULT,
                        message_id=part['id'],
                        payload={
                            'name': part['tool'],
                            'id': part.get('callID'),
                            'status': state['status'],
                            'preview': str(state.get('output', state.get('error', '')))[:8000],
                        },
                    )
                )
        if info.get('finish') == 'stop' and info.get('time', {}).get('completed'):
            trace.events.append(
                AgentTraceEvent(
                    step=step,
                    timestamp=info['time']['completed'] / 1000,
                    type=EventType.SUBMIT,
                    message_id=info['id'],
                    payload={'text': text},
                )
            )
    trace.events.sort(key=lambda event: event.timestamp)
    return trace
