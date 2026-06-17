# How to contribute

We would love to accept your patches and contributions to this project.

## Before you begin

### Review our community guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## Contribution process

### Code reviews

All submissions, including submissions by project members, require review. We
use [GitHub pull requests](https://docs.github.com/articles/about-pull-requests)
for this purpose.

### Style

-   Python code follows the
    [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
    Format with `yapf` (`based_on_style = google`, 80 columns) and lint with
    `pylint` using the repository `pylintrc`.
-   Docstrings are Google style: a one-line summary on the first line, ending
    with a period, followed by `Args:`, `Returns:`, and `Raises:` sections as
    applicable.
-   TypeScript code follows the
    [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html),
    enforced with [gts](https://github.com/google/gts).
-   `logger.debug()` messages are lowercase; `info`, `warning`, and `error`
    messages are capitalized full sentences.
-   No emojis or unicode decoration in code or logs.
-   The Rich library is used only in `engine/examples/` and `engine/dev/`,
    never in core library code.
