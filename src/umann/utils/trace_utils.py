"""Inspect helpers"""

import inspect


def str_exc(exc: Exception) -> str:
    """Convert an exception to its string representation."""
    return f"{type(exc).__name__}: {exc}"


def calling_signature() -> str:
    """Return a string representation of the calling function with its arguments.

    This function inspects the call stack to determine the function that called
    the function containing this call, along with all arguments and keyword arguments.

    Returns:
        A string in the format: "function_name(arg1, arg2, kwarg1=value1, kwarg2=value2)"

    Example:
        >>> def my_function(a, b, c=None):
        ...     sig = calling_signature()
        ...     print(sig)
        ...     # Rest of function logic
        >>> my_function(1, 2, c=3)
        my_function(1, 2, c=3)

    Note:
        Call this at the beginning of your function to capture its invocation signature.
        The function inspects two frames up the stack: frame 0 is calling_signature itself,
        frame 1 is the function that called calling_signature, and we want frame 1's info.
    """
    # Get the frame of the function that called calling_signature()
    frame = inspect.currentframe()
    if frame is None:
        return "<unknown>()"

    try:
        # Go up one level to get the caller's frame
        caller_frame = frame.f_back
        if caller_frame is None:
            return "<unknown>()"

        # Get function name from the caller's frame
        func_name = caller_frame.f_code.co_name

        # Get the argument info from the frame
        arg_info = inspect.getargvalues(caller_frame)

        # Build argument list
        args_list = []

        # Add positional arguments (excluding 'self' and 'cls' for methods)
        for arg_name in arg_info.args:
            if arg_name in ("self", "cls"):
                continue
            arg_value = arg_info.locals[arg_name]
            args_list.append(repr(arg_value))

        # Add keyword arguments if any
        if arg_info.keywords and arg_info.keywords in arg_info.locals:
            kwargs_dict = arg_info.locals[arg_info.keywords]
            for key, value in kwargs_dict.items():
                args_list.append(f"{key}={repr(value)}")

        # Build the signature string
        args_str = ", ".join(args_list)
        return f"{func_name}({args_str})"

    finally:
        # Clean up frame references to avoid reference cycles
        del frame
