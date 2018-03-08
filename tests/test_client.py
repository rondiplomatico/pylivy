import pytest
from aiohttp.web import Application, json_response

from livy.client import LivyClient
from livy.models import Session, SessionKind, Statement, StatementKind


@pytest.mark.asyncio
async def test_list_sessions(mocker, aiohttp_server):

    mock_session_json = {'mock': 'session'}
    mocker.patch.object(Session, 'from_json')

    async def list_sessions(request):
        return json_response({'sessions': [mock_session_json]})

    app = Application()
    app.router.add_get('/sessions', list_sessions)
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        sessions = await client.list_sessions()

    assert sessions == [Session.from_json.return_value]
    Session.from_json.assert_called_once_with(mock_session_json)


@pytest.mark.asyncio
async def test_get_session(mocker, aiohttp_server):

    session_id = 5
    mock_session_json = {'mock': 'session'}
    mocker.patch.object(Session, 'from_json')

    async def get_session(request):
        return json_response(mock_session_json)

    app = Application()
    app.router.add_get(f'/sessions/{session_id}', get_session)
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        session = await client.get_session(session_id)

    assert session == Session.from_json.return_value
    Session.from_json.assert_called_once_with(mock_session_json)


@pytest.mark.asyncio
async def test_create_session(mocker, aiohttp_server):

    mock_session_json = {'mock': 'session'}
    mocker.patch.object(Session, 'from_json')

    async def version(request):
        return json_response({'version': '0.5.0-incubating'})

    async def create_session(request):
        assert (await request.json()) == {'kind': 'pyspark'}
        return json_response(mock_session_json)

    app = Application()
    app.router.add_get('/version', version)
    app.router.add_post('/sessions', create_session)
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        session = await client.create_session(SessionKind.PYSPARK)

    assert session == Session.from_json.return_value
    Session.from_json.assert_called_once_with(mock_session_json)


@pytest.mark.asyncio
async def test_delete_session(mocker, aiohttp_server):

    session_id = 5

    async def delete_session(request):
        return json_response({'msg': 'deleted'})

    app = Application()
    app.router.add_delete(f'/sessions/{session_id}', delete_session)
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        await client.delete_session(session_id)


@pytest.mark.asyncio
async def test_list_statements(mocker, aiohttp_server):

    session_id = 5
    mock_statement_json = {'mock': 'statement'}
    mocker.patch.object(Statement, 'from_json')

    async def list_statements(request):
        return json_response({'statements': [mock_statement_json]})

    app = Application()
    app.router.add_get(f'/sessions/{session_id}/statements', list_statements)
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        statements = await client.list_statements(session_id)

    assert statements == [Statement.from_json.return_value]
    Statement.from_json.assert_called_once_with(
        session_id,
        mock_statement_json
    )


@pytest.mark.asyncio
async def test_get_statement(mocker, aiohttp_server):

    session_id = 5
    statement_id = 10
    mock_statement_json = {'mock': 'statement'}
    mocker.patch.object(Statement, 'from_json')

    async def get_statement(request):
        return json_response(mock_statement_json)

    app = Application()
    app.router.add_get(
        f'/sessions/{session_id}/statements/{statement_id}',
        get_statement
    )
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        statement = await client.get_statement(session_id, statement_id)

    assert statement == Statement.from_json.return_value
    Statement.from_json.assert_called_once_with(
        session_id,
        mock_statement_json
    )


@pytest.mark.asyncio
async def test_create_statement(mocker, aiohttp_server):

    session_id = 5
    code = 'some code'
    mock_statement_json = {'mock': 'statement'}
    mocker.patch.object(Statement, 'from_json')

    async def version(request):
        return json_response({'version': '0.5.0-incubating'})

    async def create_statement(request):
        assert (await request.json()) == {'code': code, 'kind': 'pyspark'}
        return json_response(mock_statement_json)

    app = Application()
    app.router.add_get('/version', version)
    app.router.add_post(f'/sessions/{session_id}/statements', create_statement)
    server = await aiohttp_server(app)

    async with server:
        client = LivyClient(str(server.make_url('/')))
        statement = await client.create_statement(
            session_id,
            code,
            StatementKind.PYSPARK
        )

    assert statement == Statement.from_json.return_value
    Statement.from_json.assert_called_once_with(
        session_id,
        mock_statement_json
    )
