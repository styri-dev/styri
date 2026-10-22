# The package's metadata, for pip and for colcon / the ROS build farm
# (ament_python). Keep the version in step with package.xml.
from setuptools import setup

package_name = "styri_bridge"

setup(
    name=package_name,
    version="0.2.1",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    # rclpy and ROS message packages come from the ROS 2 distro, not PyPI.
    install_requires=["websockets>=13,<18", "PyYAML>=5.4"],
    extras_require={"test": ["pytest>=8"]},
    zip_safe=True,
    maintainer="Styri",
    maintainer_email="hello@styri.dev",
    description="Styri Core: an offline ROS 2 web dashboard and read-only operator panel.",
    license="Apache-2.0",
    entry_points={"console_scripts": ["styri = styri_bridge.__main__:main",
                                      "styri-bridge = styri_bridge.__main__:main"]},
)
