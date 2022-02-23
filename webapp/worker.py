import sys
import time
import traceback
from multiprocessing import Process

from flask import Blueprint
from flask import current_app as app

from webapp.managers import AppDbContext, TaskStatusEnum
from webapp.models import Group, Message, Task, Variant
from webapp.utils import create_session_manually


blueprint = Blueprint("worker", __name__)


def decrypt_exception() -> str:
    exc_type, exc_value, exc_traceback = sys.exc_info()
    lines = traceback.format_exception(
        exc_type, exc_value, exc_traceback)
    log = "".join("!! " + line for line in lines)
    return log


def check_solution(
        core_path: str,
        group: Group,
        task: Task,
        variant: Variant,
        message: Message):
    if core_path not in sys.path:
        sys.path.insert(1, core_path)
    from check_solution import check_solution
    (ok, error) = check_solution(
        group=group.title,
        task=task.id,
        variant=variant.id,
        code=message.code,
    )
    return (ok, error)


def load_tests(core_path: str):
    if core_path not in sys.path:
        sys.path.insert(1, core_path)
    from loaded_tests import GROUPS, TASKS
    return GROUPS, TASKS


def process_pending_messages(db: AppDbContext, core_path: str):
    pending_messages = db.messages.get_pending_messages_unique()
    message_count = len(pending_messages)
    if message_count > 0:
        print(f"Processing {message_count} incoming messages...")
    for message in pending_messages:
        group = db.groups.get_by_id(message.group)
        task = db.tasks.get_by_id(message.task)
        variant = db.variants.get_by_id(message.variant)
        print(f"g-{message.group}, t-{message.task}, v-{message.variant}")
        try:
            (ok, error) = check_solution(core_path, group, task, variant, message)
            print(f"Check result: {ok}, {error}")
            status = TaskStatusEnum.Checked if ok else TaskStatusEnum.Failed
            db.messages.mark_as_processed(
                task=message.task,
                variant=message.variant,
                group=message.group,
            )
            db.statuses.update_status(
                task=message.task,
                variant=message.variant,
                group=message.group,
                status=status,
                output=error,
            )
        except BaseException:
            exception = decrypt_exception()
            print(f"Error occured while checking for messages: {exception}")


def background_worker(connection_string: str, core_path: str):
    print(f"Starting background worker for database: {connection_string}")
    while True:
        time.sleep(10)
        with create_session_manually(connection_string) as session:
            db = AppDbContext(session)
            try:
                process_pending_messages(db, core_path)
            except BaseException:
                exception = decrypt_exception()
                print(f"Error orccured inside the loop: {exception}")


@blueprint.before_app_first_request
def start_background_worker():
    connection_string = app.config["CONNECTION_STRING"]
    core_path = app.config["CORE_PATH"]
    process = Process(
        target=background_worker, args=(
            connection_string, core_path))
    process.start()
