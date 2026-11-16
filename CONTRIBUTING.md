# Contributing to M3U Stream Checker

Contributions, bug reports and design feedback are welcome.

1. Open an issue explaining the problem, with reproduction steps and expected output. Remove personal URLs, credentials and tokens.
2. Make a small branch and keep unrelated UI and parsing logic unchanged.
3. Test on a small, authorised M3U file. Clearly distinguish HTTP reachability from actual video playback.
4. Include your operating system, Python version, and a description of test results in the pull request.
5. Do not commit generated PyInstaller `build/`, `dist/`, user-specific paths, third-party playlist archives or binary copies.

Good first tasks: improve UI readability, safer progress/cancellation, M3U metadata handling, network timeout diagnostics, documentation and automated tests.

See the [GPLv3 licence](LICENSE). Contributed code needs to be compatible with the project's stated licence.
