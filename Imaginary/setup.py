from epsilon.setuphelper import autosetup

import imaginary

distobj = autosetup(
    name="Imaginary",
    version=imaginary.version.short(),
    maintainer="Divmod, Inc.",
    maintainer_email="support@divmod.org",
    url="http://divmod.org/trac/wiki/DivmodImaginary",
    license="MIT",
    platforms=["any"],
    description=imaginary.__doc__,
    classifiers=[
        "Intended Audience :: Developers",
        "Intended Audience :: Education",
        "Programming Language :: Python",
        "Development Status :: 2 - Pre-Alpha",
        "Topic :: Games/Entertainment",
        "Topic :: Games/Entertainment :: Multi-User Dungeons (MUD)",
        "Topic :: Games/Entertainment :: Puzzle Games",
        "Topic :: Games/Entertainment :: Real Time Strategy",
        "Topic :: Games/Entertainment :: Role-Playing",
        "Topic :: Games/Entertainment :: Simulation"])
