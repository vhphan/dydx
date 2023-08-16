from functools import wraps

from program.func_messaging import send_message


def exception_handler(err):
    pass


def on_error_abort(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        func_name = func.__name__
        print(f"Running {func_name}...")
        try:
            return func(*args, **kwargs)
        except Exception as err:
            # my_exception_handler(e)
            print(f"Error running {func_name}.")
            print(f"Exception: {err}")
            send_message(f"Error running {func_name}.")
            send_message(f"Exception: {err}")
            exit(1)

    return func_wrapper


def on_error_abort_with_error_func(error_func):
    def decorator(func):
        @wraps(func)
        def func_wrapper(*args, **kwargs):
            func_name = func.__name__
            print(f"Running {func_name}...")
            try:
                return func(*args, **kwargs)
            except Exception as err:
                print(f"Error running {func_name}.")
                print(f"Exception: {err}")
                send_message(f"Error running {func_name}.")
                send_message(f"Exception: {err}")
                error_func()
                exit(1)

        return func_wrapper

    return decorator
