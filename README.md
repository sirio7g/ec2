ec2
===

ec2 is a simple shell script that helps you out to log into your EC2 instances just picking them from a list.

![Screenshot](https://raw.github.com/sirio7g/ec2/master/docs/login.png "Screenshot")

# Setting up

ec2 script is built on top of boto library so, first of all, install them using pip:

```
pip install boto
```

If you have the Mountain Lion version of OsX you might need to export the variable as following

```
export PYTHONPATH=/usr/bin/python2.7
export PYTHONPATH=${PYTHONPATH}:$HOME/code/python/boto
```

change the python version according to your own.

Since ec2 script wants to be a very quick shortcut to jump into your instances, it uses a property file in order to load default settings as default username, default pem file, default region, etc. then move in your home directory the .ec2-default.props and edit it.

Then you have to add the ec2 directory to your PATH env variable:

export PATH=$PATH:/path_of_ec2/bin/

you can do it persisten by adding the above line to your .bash_profile or .profile file.

# Usage

```
ec2 [-u user] [-x] [-c "command"] [eu|us|us-west-1|region]

Arguments:
	-u user
	-k PEM file
	-x Export display
	-c "command (sent by ssh)"
```

ec2 allows to run command (by ssh) on a server or even onto a list of servers using the “-c” argument, look at the example below:

![Screenshot](https://raw.github.com/sirio7g/ec2/master/docs/logini2.png "Screenshot")
