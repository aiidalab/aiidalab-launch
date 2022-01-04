# AiiDAlab Launch

AiiDAlab Launch makes it easy to run AiiDAlab on your own workstation or laptop.

## Getting Started

To use AiiDAlab launch you will have to

1. [Install Docker on your workstation or laptop.](https://docs.docker.com/get-docker/)
2. Install AiiDAlab launch and start AiiDAlab with

    ```bash
    pip install aiidalab-launch
    aiidalab-launch start
    ```
3. Follow the instructions on screen to open AiiDAlab in the browser.

See `aiidalab-launch --help` for detailed help.

### Instance Management

You can inspect the status of all configured AiiDAlab profiles with:

```console
aiidalab-launch status
```

### Profile Management

The tool allows to manage multiple profiles, e.g., with different home directories or ports.
See `aiidalab-launch profiles --help` for more information.

### Forward AiiDAlab from a remote server via SSH

Please see [here](ssh-forward.md) for instructions on how to run AiiDAlab on a remote machine and then forward it to your local terminal.

## Authors

* **Carl Simon Adorf (EPFL)** - [@csadorf](https://github.com/csadorf)

See also the list of [contributors](https://github.com/aiidalab/aiidalab-launch/contributors).


## Citation

Users of AiiDAlab are kindly asked to cite the following publication in their own work:

A. V. Yakutovich et al., Comp. Mat. Sci. 188, 110165 (2021).
[DOI:10.1016/j.commatsci.2020.110165](https://doi.org/10.1016/j.commatsci.2020.110165)

## Contact

aiidalab@materialscloud.org

## For maintainers

To create a new release, clone the repository, install development dependencies with `pip install -e '.[dev]'`, and then execute `bumpver update`.
This will:

  1. Create a tagged release with bumped version and push it to the repository.
  2. Trigger a GitHub actions workflow that creates a GitHub release and publishes it on PyPI.

Additional notes:

  - Use the `--dry` option to preview the release change.
  - The release tag (e.g. a/b/rc) is determined from the last release.
    Use the `--tag` option to switch the release tag.

## MIT License

Copyright (c) 2021 Carl Simon Adorf (EPFL)

All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Acknowledgements

This work is supported by the
[MARVEL National Centre for Competency in Research](<http://nccr-marvel.ch>) funded by the [Swiss National Science Foundation](<http://www.snf.ch/en>),
the MARKETPLACE project funded by [Horizon 2020](https://ec.europa.eu/programmes/horizon2020/) under the H2020-NMBP-25-2017 call (Grant No. 760173),
as well as by the [MaX
European Centre of Excellence](<http://www.max-centre.eu/>) funded by the Horizon 2020 EINFRA-5 program,
Grant No. 676598.

<div style="text-align:center">
 <img src="logos/MARVEL.png" alt="MARVEL" height="75px">
 <img src="logos/MaX.png" alt="MaX" height="75px">
 <img src="logos/MarketPlace.png" alt="MarketPlace" height="75px">
</div>
