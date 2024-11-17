from distutils.core import setup
from setuptools import find_packages

setup(
	name='gkbus_test',
	packages=find_packages(),
	version='0.2.6',
	description='High-level KWP over K-line/CANbus library',
	description_content_type='text/markdown',
	author='Dante383',
	install_requires=['scapy==2.5.0', 'pyserial==3.5']
)
