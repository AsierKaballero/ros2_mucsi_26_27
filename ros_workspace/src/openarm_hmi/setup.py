import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'openarm_hmi'


def arbol(origen):
    """Instala una carpeta respetando su estructura (web/, con los vendor de three.js)."""
    datos = []
    for carpeta, _, ficheros in os.walk(origen):
        if ficheros:
            datos.append((
                os.path.join('share', package_name, carpeta),
                [os.path.join(carpeta, f) for f in ficheros],
            ))
    return datos


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ] + arbol('web'),
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='laboratorio',
    maintainer_email='laboratorio@todo.todo',
    description='HMI web para los brazos OpenArm del laboratorio',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'hmi_servidor = openarm_hmi.principal:main',
            'camara_simulada = openarm_hmi.nodos.camara_simulada:main',
            'prueba_movimiento = openarm_hmi.scripts.prueba_movimiento:main',
        ],
    },
)
