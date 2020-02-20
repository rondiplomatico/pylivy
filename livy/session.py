import time
import json
from typing import Any, Dict, List, Iterable, Iterator, Optional

import pandas

from livy.client import LivyClient, Auth, Verify
from livy.models import SessionKind, SessionState, StatementState, Output


SERIALISE_DATAFRAME_TEMPLATE_SPARK = "{}.toJSON.collect.foreach(println)"
SERIALISE_DATAFRAME_TEMPLATE_PYSPARK = """
for _livy_client_serialised_row in {}.toJSON().collect():
    print(_livy_client_serialised_row)
"""
SERIALISE_DATAFRAME_TEMPLATE_SPARKR = r"""
cat(unlist(collect(toJSON({}))), sep = '\n')
"""


def serialise_dataframe_code(
    dataframe_name: str, session_kind: SessionKind
) -> str:
    try:
        template = {
            SessionKind.SPARK: SERIALISE_DATAFRAME_TEMPLATE_SPARK,
            SessionKind.PYSPARK: SERIALISE_DATAFRAME_TEMPLATE_PYSPARK,
            SessionKind.PYSPARK3: SERIALISE_DATAFRAME_TEMPLATE_PYSPARK,
            SessionKind.SPARKR: SERIALISE_DATAFRAME_TEMPLATE_SPARKR,
        }[session_kind]
    except KeyError:
        raise RuntimeError(
            f"read not supported for sessions of kind {session_kind}"
        )
    return template.format(dataframe_name)


def deserialise_dataframe(text: str) -> pandas.DataFrame:
    rows = []
    for line in text.split("\n"):
        if line:
            rows.append(json.loads(line))
    return pandas.DataFrame.from_records(rows)


def dataframe_from_json_output(json_output: dict) -> pandas.DataFrame:
    try:
        fields = json_output["schema"]["fields"]
        columns = [field["name"] for field in fields]
        data = json_output["data"]
    except KeyError:
        raise ValueError("json output does not match expected structure")
    return pandas.DataFrame(data, columns=columns)


def polling_intervals(
    start: Iterable[float], rest: float, max_duration: float = None
) -> Iterator[float]:
    def _intervals():
        yield from start
        while True:
            yield rest

    cumulative = 0.0
    for interval in _intervals():
        cumulative += interval
        if max_duration is not None and cumulative > max_duration:
            break
        yield interval


class LivySession:
    """Manages a remote Livy session and high-level interactions with it.

    The py_files, files, jars and archives arguments are lists of URLs, e.g.
    ["s3://bucket/object", "hdfs://path/to/file", ...] and must be reachable by
    the Spark driver process.  If the provided URL has no scheme, it's
    considered to be relative to the default file system configured in the Livy
    server.

    URLs in the py_files argument are copied to a temporary staging area and
    inserted into Python's sys.path ahead of the standard library paths. This
    allows you to import .py, .zip and .egg files in Python.

    URLs for jars, py_files, files and archives arguments are all copied to the
    same working directory on the Spark cluster.

    The driver_memory and executor_memory arguments have the same format as JVM
    memory strings with a size unit suffix ("k", "m", "g" or "t") (e.g. 512m,
    2g).

    See https://spark.apache.org/docs/latest/configuration.html for more
    information on Spark configuration properties.

    :param url: The URL of the Livy server.
    :param auth: A requests-compatible auth object to use when making requests.
    :param verify: Either a boolean, in which case it controls whether we
        verify the server’s TLS certificate, or a string, in which case it must
        be a path to a CA bundle to use. Defaults to ``True``.
    :param kind: The kind of session to create.
    :param proxy_user: User to impersonate when starting the session.
    :param jars: URLs of jars to be used in this session.
    :param py_files: URLs of Python files to be used in this session.
    :param files: URLs of files to be used in this session.
    :param driver_memory: Amount of memory to use for the driver process (e.g.
        '512m').
    :param driver_cores: Number of cores to use for the driver process.
    :param executor_memory: Amount of memory to use per executor process (e.g.
        '512m').
    :param executor_cores: Number of cores to use for each executor.
    :param num_executors: Number of executors to launch for this session.
    :param archives: URLs of archives to be used in this session.
    :param queue: The name of the YARN queue to which submitted.
    :param name: The name of this session.
    :param spark_conf: Spark configuration properties.
    :param echo: Whether to echo output printed in the remote session. Defaults
        to ``True``.
    :param check: Whether to raise an exception when a statement in the remote
        session fails. Defaults to ``True``.
    :param resumeSessionID: A session ID to resume to, instead of creating a new 
        session. Will create a new session if the session does not exist (anymore)
    """

    def __init__(
        self,
        url: str,
        auth: Auth = None,
        verify: Verify = True,
        kind: SessionKind = SessionKind.PYSPARK,
        proxy_user: str = None,
        jars: List[str] = None,
        py_files: List[str] = None,
        files: List[str] = None,
        driver_memory: str = None,
        driver_cores: int = None,
        executor_memory: str = None,
        executor_cores: int = None,
        num_executors: int = None,
        archives: List[str] = None,
        queue: str = None,
        name: str = None,
        spark_conf: Dict[str, Any] = None,
        echo: bool = True,
        check: bool = True,
        resumeId: int = None
    ) -> None:
        self.client = LivyClient(url, auth, verify=verify)
        self.kind = kind
        self.proxy_user = proxy_user
        self.jars = jars
        self.py_files = py_files
        self.files = files
        self.driver_memory = driver_memory
        self.driver_cores = driver_cores
        self.executor_memory = executor_memory
        self.executor_cores = executor_cores
        self.num_executors = num_executors
        self.archives = archives
        self.queue = queue
        self.name = name
        self.spark_conf = spark_conf
        self.echo = echo
        self.check = check
        self.resumeSessionID = resumeId
        self.session_id: Optional[int] = None

    def __enter__(self) -> "LivySession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def start(self) -> None:
        """Create the remote Spark session and wait for it to be ready."""
        session = None
        if self.resumeSessionID is not None:
            session = self.client.get_session(self.resumeSessionID)
            if session is None:
                print("Resuming session #%s failed: Session does not exist. Creating a new session." % self.resumeSessionID)
            if session is not None and session.state in [SessionState.DEAD, SessionState.KILLED, SessionState.ERROR]:
                print("Resuming session #%s failed: %s. Creating a new session." % (self.resumeSessionID, session.state))
                session = None
        
        if session is None:
            session = self.client.create_session(
                self.kind,
                self.proxy_user,
                self.jars,
                self.py_files,
                self.files,
                self.driver_memory,
                self.driver_cores,
                self.executor_memory,
                self.executor_cores,
                self.num_executors,
                self.archives,
                self.queue,
                self.name,
                self.spark_conf,
            )
        self.session_id = session.session_id

        not_ready = {SessionState.NOT_STARTED, SessionState.STARTING}
        intervals = polling_intervals([0.1, 0.2, 0.3, 0.5], 1.0)

        while self.state in not_ready:
            time.sleep(next(intervals))

    @property
    def state(self) -> SessionState:
        """The state of the managed Spark session."""
        if self.session_id is None:
            raise ValueError("session not yet started")
        session = self.client.get_session(self.session_id)
        if session is None:
            raise ValueError("session not found - it may have been shut down")
        return session.state

    def close(self) -> None:
        """Kill the managed Spark session."""
        if self.session_id is not None:
            self.client.delete_session(self.session_id)
        self.client.close()

    def run(self, code: str) -> Output:
        """Run some code in the managed Spark session.

        :param code: The code to run.
        """
        output = self._execute(code)
        if self.echo and output.text:
            print(output.text)
        if self.check:
            output.raise_for_status()
        return output

    def read(self, dataframe_name: str) -> pandas.DataFrame:
        """Evaluate and retrieve a Spark dataframe in the managed session.

        :param dataframe_name: The name of the Spark dataframe to read.
        """
        code = serialise_dataframe_code(dataframe_name, self.kind)
        output = self._execute(code)
        output.raise_for_status()
        if output.text is None:
            raise RuntimeError("statement had no text output")
        return deserialise_dataframe(output.text)

    def read_sql(self, code: str) -> pandas.DataFrame:
        """Evaluate a Spark SQL satatement and retrieve the result.

        :param code: The Spark SQL statement to evaluate.
        """
        if self.kind != SessionKind.SQL:
            raise ValueError("not a SQL session")
        output = self._execute(code)
        output.raise_for_status()
        if output.json is None:
            raise RuntimeError("statement had no JSON output")
        return dataframe_from_json_output(output.json)

    def _execute(self, code: str) -> Output:
        if self.session_id is None:
            raise ValueError("session not yet started")

        statement = self.client.create_statement(self.session_id, code)

        intervals = polling_intervals([0.1, 0.2, 0.3, 0.5], 1.0)

        def waiting_for_output(statement):
            not_finished = statement.state in {
                StatementState.WAITING,
                StatementState.RUNNING,
            }
            available = statement.state == StatementState.AVAILABLE
            return not_finished or (available and statement.output is None)

        while waiting_for_output(statement):
            time.sleep(next(intervals))
            statement = self.client.get_statement(
                statement.session_id, statement.statement_id
            )

        if statement.output is None:
            raise RuntimeError("statement had no output")

        return statement.output
