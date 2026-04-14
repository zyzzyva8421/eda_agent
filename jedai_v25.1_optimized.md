# JedAI Platform (Server) User Guide
**Product Version 25.10 | May 2025**

> Cadence Joint Enterprise Data and AI (JedAI) Platform
> 数据注册、探索和分析的统一基础设施和服务

---
## Introduction to JedAI

Cadence Joint Enterprise Data and AI (JedAI) Platform is a data platform for data registration,
exploration, and analysis. It comes with toolsets that enable users to register data within a JedAI
system. In addition, this system delivers built-in applications to consume and analyze the data
along with APIs for user-driven data exploration and tailored application creation.
The architecture diagram below describes the different layers of the JedAI system. The data storage
layer is built on top of NFS or local file system. Based on the workload, JedAI can be installed and
run on a single-node machine or a multiple-node cluster. Within the cluster mode, the cluster admin
and authentication components are responsible for managing user access and launching different
components within the cluster. The key services in JedAI are:
Catalog service - Responsible for managing the metadata for the data and other services. The
Catalog API is provided for manipulating the metadata.
Analytics engine - Responsible for running jobs either through Pandas or Spark, including
jobs for ETL (Extraction, Transformation and Load) and consumption. The App sever provides
the API to start/terminate the job on the platform.
Pipeline/workflow service - Allows you to define a no-code/low-code ETL process that can be
run on the analytics engine.
Dashboard service - Provides a way to visualize the sample dataset and flash out an idea that
can later be built as a user-friendly Web app.
App component - Delivers the Web app after it is built, providing a standard way for end users
to consume the data.
Notebook service - Provides a python interface to explore the data.
Machine Learning Operation (MLOps) service - Allows you to build an end-to-end machine
learning pipeline and track the history of experiment of the machine learning model.

---
## Getting Started

What's Included
License Requirements
Installation and Operation
Setting Up the Run-Time Environment
What's Included
An installation tarball is included in the JedAI release package.
You can choose either of the following installation modes:
Single-node: In the Single-node mode, all services run on one machine. However, you do
have an option to add Spark work nodes for more computation power. The tarball for the
Single-node mode installation has the JEDAIServer64b<version>lnx86.t.Z name format.
Cluster: The JedAI Cluster mode runs services on the Kubernetes cluster. In this mode, you
can run services on multiple containers, as well as run Spark compute containers across
multiple nodes. The tarball for the Cluster mode installation has the
JEDAIServerCluster64b<version>lnx86.t.Z name format.
The installation tarballs for the Single-node and Cluster modes are different.
License Requirements
The Cadence Joint Enterprise Data and AI (JedAI) Platform requires one or more of the following
licenses to be available on the license server:
| Product # | Product Name | License Feature |
|---|---|---|
| JEDAI100 | Cadence JedAI Platform Streaming | JedAI_Streaming |
| JEDAI200 | Cadence JedAI Platform | JedAI_Infrastructure_Server |
| JEDAI250 | Cadence JedAI Platform User 10 | JedAI_User, quantity 10 + |
| JEDAI260 | Cadence JedAI Platform User 100 | JedAI_User, quantity 100 + |
| JEDAI300 | Cadence JedAI Platform Developer | JedAI_Developer |
| JEDAI400 | Cadence JedAI Platform Silicon | JedAI_App_SiliconSight + JedAI_Access |
| JEDAI410 | Cadence JedAI Platform | JedAI_App_Dashboard + JedAI_Access |
| JEDAI415 | Cadence JedAI Platform Clock | JedAI_App_ClockDoctor + JedAI_Access |
| JEDAI420 | Cadence JedAI Platform Timing | JedAI_App_TimingMatrix + JedAI_Access |
| JEDAI425 | Cadence JedAI Platform PPA | JedAI_App_PPACompare + |
| JEDAI430 | Cadence JedAI Platform | JedAI_App_CongAnalyzer + |
| JEDAI435 | Cadence JedAI Platform Budget | JedAI_App_BudgetAnalyzer + |
| JEDAI440 | Cadence JedAI Platform Buffer | JedAI_App_BufferTree + JedAI_Access |
| JEDAI445 | Cadence JedAI Platform Parameter | JedAI_App_ParameterAnalysis + | the following environment variables are set:
setenv LD_LIBRARY_PATH <folder_for_libcdsCommon_sh.so>:
$LD_LIBRARY_PATH
Includes the library libcdsCommon_sh.so in the shared library path
setenv PATH <cds_root>:$PATH
Makes sure the PATH includes the executable cds_root
setenv CDS_LIC_FILE <port@server>
Makes sure the cds license server and port is defined
If the variables mentioned above are not set up correctly, an error message is displayed.
Related Information
Installation and Operation
Setting Up the Run-Time Environment
Installation and Operation
Single-node Mode Installation
Cluster Mode Installation
Single-node Mode Installation
Prerequisites
Installing from Scratch
Upgrading an Existing Instance
Installing or Upgrading with InstallScape
Managing the Service
Backing Up and Restoring JedAI Data
Forcing JedAI To Stop
Enabling Spark Cluster in Single-node JedAI (optional)
Dynamic App Server
Enabling HTTPS (TLS/SSL)
Enabling LDAP Authentication
Prerequisites
Hardware Requirements
CPU cores: 4 minimum
Memory: 32GB minimum
Hard Disk: 40GB minimum (only for system artifacts, recommend a large disk for storing your
ingested data)
Open ports for network access within organization, such as 5000-5020. Ensure these ports
are not occupied by other processes.
If the ports are occupied and need to be changed, open those ports and modify the
corresponding port numbers in the configuration file (lite_config.yml).
Operating System
Centos (RHEL) = 8.4
Software Requirements
Python 3.9.6
Npm 6.14.11
Nginx 1.20.0
The software mentioned above are installed as part of the installation.
GCC 4.8.5 or above
libstdc++ 4.8.5 or above
tar 1.26 or above
User Permission Requirements
A valid Linux non-root user
License Server Accessibility
JedAI uses the default Cadence license server environment. Make sure to obtain your license
server information before you start the installation.
Installing from Scratch
1. Copy and unzip the tarball on the target machine:
UNIX> tar -xvzf install.tar.gz
Do not unzip it to the JEDAI_INSTALL_DIR. Create a fresh directory outside the area
where you want to install the JedAI server.
2. Modify the install folder and license in install/config.sh.
The default install path for JedAI is /opt/cadence, and usually, it is a local path. It is
strongly recommended that you change to a shared nfs folder to which you have read,
write, and execute permissions.
a. The JEDAI_INSTALL_DIR path can be of any length. However, the length of
the JEDAI_RUNTIME_DIR path, which by default is
$JEDAI_INSTALL_DIR/jedai/data/run, cannot exceed 97 characters. If the
JEDAI_RUNTIME_DIR path is exceeding the limit, set it to a shorter path. Note
that JEDAI_RUNTIME_DIR is used to store temporary files during run time and
setting it to another path will not affect the data that you want to store or
read.
b. Make sure the license server is accessible from the current machine. The
CDS_LIC_FILE indicates the location of the Cadence license. For example,
5280@sjflex1 indicates the license exists at server sjflex1, port 5280.
##config.sh
export JEDAI_INSTALL_DIR=/opt/cadence
export CDS_LIC_FILE={license_file}
3. Run the install script.
UNIX> bash install.sh
Once the package is installed successfully, JedAI will automatically start the service and
display the services running on corresponding server and ports, as shown in the screenshot
below.
Record the server and port value for each component for later use.
4. Modify the install/lite_config.yml if the network port number needs to be changed or to
disable TLS (https) by commenting out the tls section (optional). You can copy the file to a
private location and modify it:
web_server:
port: 5000
upload_file_limit: 40G
# tls:
#   port: 5009
notebooks:
dummy: Cadence!
spawner: local
port: 5001
hub_port: 5010
api_port: 5011
mlflow:
port: 5003
manager_rest_api:
port: 5004
catalog:
port: 5005
admin_portal:
port: 5006
password: admin
app_server:
log_level: INFO
tmp_dir: /tmp
flow_server:
port: 5008
workflow:
port: 5012
postgres_port: 5013
redis_port: 5014
superset:
port: 5015
hive:
port: 5016
monitor_server:
port: 5017
websocket:
port: 5018
rpc_server:
port: 5019
5. Specify the required environment settings:
JEDAI_CONFIG_PATH: Point to the full path of the lite config yaml file. By default, it is set to
$JEDAI_INSTALL_DIR/jedai/lite_config.yml.
JEDAI_DATA_DIR: Point to a writable directory. As JedAI will save all data in this directory, it
should be sufficiently large. By default, it is set to $JEDAI_INSTALL_DIR/jedai/data.
6. Start the services:
bash:
UNIX> source $JEDAI_INSTALL_DIR/setup.sh && jedai start –-daemon && sleep 20 &&
jedai status
UNIX> export JEDAI_CONFIG_PATH=<full_path_of_lite_config.yml> # the default is
$JEDAI_INSTALL_DIR/jedai/lite_config.yml
UNIX> export JEDAI_DATA_DIR=<full_path_of_users_data_dir> # the default is
$JEDAI_INSTALL_DIR/jedai/data, we recommend to change it
csh:
UNIX> source $JEDAI_INSTALL_DIR/setup.csh && jedai start –-daemon && sleep 20 &&
jedai status
UNIX> setenv JEDAI_CONFIG_PATH <full_path_of_lite_config.yml> # the default is
$JEDAI_INSTALL_DIR/jedai/lite_config.yml
UNIX> setenv JEDAI_DATA_DIR <full_path_of_users_data_dir> # the default is
$JEDAI_INSTALL_DIR/jedai/data, we recommend to change it
As shown in the example, if you have not changed the port number, you should be able to
access the web server at http://{<server>}:5000 after JedAI starts.
To check the {<server>} URL, use the jedai status command. For more details on
the jedai command, see the Managing the Service section.
The installation package includes Firefox. If you do not have a modern browser
installed in your environment, you can launch the Firefox browser using the following
command:
UNIX> $JEDAI_INSTALL_DIR/jedai/tools.lnx86/firefox/firefox
7. Create a user and log in using the JedAI interface. After JedAI starts, you need to create a
user to access the front end.
a. Create a user by using the following command:
Use the following command:
<PASSWORD>]
The admin user is created by default during the installation with the
password provided in the lite_config.yml file for admin_portal.
It is recommended that you change the default admin password by using
the following command:
password <PASSWORD>]
The system will first verify the user with the old password:
The same method can be used for changing the password of any other
user.
b. Log in to the JedAI front end with the username and password.
Upgrading an Existing Instance
1. Stop the JedAI services first.
UNIX> jedai stop; deactivate
2. Follow Steps 1 and 2 of Installing from Scratch. Note that the JEDAI_DATA_DIR value must be
the same as the previous install. The JEDAI_DATA_DIR is set to
$JEDAI_INSTALL_DIR/jedai/data in installation by default. If you set JEDAI_INSTALL_DIR to
another location before the upgrade, you need to reset JEDAI_DATA_DIR manually to the old
location after the installation and start JedAI to continue using the old data. All files except
those under $JEDAI_DATA_DIR would be covered by the new files from the new install.
3. Set up JEDAI_DATA_BACKUP_PATH.
UNIX> export JEDAI_DATA_BACKUP_PATH=/tmp/jedai_backup
4. Add -upgrade to the install command:
5. Follow Step 5 of Installing from Scratch to start the instance.
Installing or Upgrading with InstallScape
1. Download InstallScape from downloads.cadence.com and install. Link to Cadence's
download center to download JedAI.
2. Install JedAI with InstallScape by using one of the following modes:
InstallScape UI mode - For this mode:
a. Click Configure releases on the toolbar, then select the JEDAI release and click
Continue.
b. In the next page, click Configure to start the JedAI installation.
Command-line mode - For this mode, run the following commands to start the
installation:
UNIX> cd <install_tarball_location>
UNIX> source ./tools.lnx86/jedAI/bin/jedai_configure.sh
3. In both the InstallScape UI and command line modes, you need to specify the location where
JedAI would be installed and the install mode as shown below:
Here:
The Where do you want to install jedAI question refers to the install location
or JEDAI_INSTALL_DIR as mentioned in the Installing from Scratch section.
For the Do you want to upgrade jedAI question, "yes" equals to the upgrade mode and
"no" equals to the install mode. If you need to enter the upgrade mode, be sure to
confirm:
a. The previous jedAI instance has been stopped.
b. The answer to Where do you want to install jedAI question is the same as
specified while installing the previous version.
4. After the installation is complete, run the following command to start jedai:
bash:
UNIX> source $JEDAI_INSTALL_DIR/setup.sh && jedai start –-daemon && sleep 20 &&
jedai status
csh:
UNIX> source $JEDAI_INSTALL_DIR/setup.csh && jedai start –-daemon && sleep 20 &&
jedai status
The <install_tarball_location> is only used for unpacking installation package, and
the actual installation path is JEDAI_INSTALL_DIR. So it is strongly suggested to set the
JEDAI_INSTALL_DIR to a new directory and not as the sub-directory of the
<install_tarball_location>.
If a ports occupation error is reported in jedai start, update the occupied ports to
other ports in the
<install_tarball_location>/tools.lnx86/jedAI/lite_config.yml and try running
Managing the Service
To manage the JedAI service, you need to first set up the correct environment by running the
following command:
bash:
UNIX> source $JEDAI_INSTALL_PATH/setup.sh
csh:
UNIX> source $JEDAI_INSTALL_PATH/setup.csh
Once the environment is set, you can run the jedai command to start, stop, check status, and so on.
Below is the help message for the command:
{init,start,status,restart,stop,add,load_example,set} ...
optional arguments:
directory of JedAI installation
directory for configuration, database, log, and runtime data
Commands:
init: Initializes JedAI. Once JedAI is installed, you do not need to run this command anymore.
start: Starts all the services on JedAI.
status: Checks whether all JedAI services are running. If yes, it shows the services' URL.
However, if the management service is not running, it shows the following message:
restart: Restarts the JedAI services.
stop: Stops the JedAI services.
add: Adds a work node for Spark support in JedAI. Refer to the Enabling Spark Support in
Single-node JedAI section for details.
load_example: Loads examples for demonstrating JedAI capabilities. You should be able to
see the three datasets listed in the Catalog page. Usage:
jedai load_example
set: Sets variables; currently only the loglevel variable can be set. Use this variable tol
change the logging level of new application servers. Example:
jedai set loglevel=DEBUG.
Backing Up and Restoring JedAI Data
Backup
Backs up the JedAI data from the current running instance.
Optional arguments:
Restore
Restores the JedAI data to the current running instance.
Optional arguments:
Default: False
up data.
Forcing JedAI To Stop
bash:
UNIX> source $JEDAI_INSTALL_PATH/setup.sh
Enabling Spark Cluster in Single-node JedAI (optional)
1. Modify lite_config.yaml by adding/modifying the following lines:
spark_coordinator:
port: 7077
webui_port: 5021
spark_worker:
cores: "8"    # number of cores used by spark on each spark worker
memory: "64G" # total size of memory used by spark on each spark worker,
ssh_hosts:    # hostname if using ssh; passwordless authentication must be set
up correctly
# if not using ssh, please skip it
- host1     # do not include the coordinator node in the hosts here
- host2
lsf:
bsub_exec: /path/to/bsub     # full path of bsub
bsub_queue: interactive      # bsub queue to be used
bsub_args: “-W 240:00 -P Dev:RD:Test” # arguments to bsub
bsub_resource: OSREL==EE70             # resources
2. Stop and start JedAI
UNIX> jedai stop
UNIX> jedai status
Output on the screen:
spark_coordinator xxxx http://jedai_server:5018: active
spark_worker-<hostname>: active
Initially, spark_coordinator and one spark_worker will be running if ssh_hosts is not defined.
3. Add, stop, or restart a spark_worker.
You must first add a spark_worker, before you can stop or restart it.
Adding a spark_worker:
or
Stopping a spark_worker:
UNIX> jedai stop spark_worker-host1
Restarting a spark_worker:
UNIX> jedai restart spark_worker-host1
Dynamic App Server
JedAI supports the dynamic app server for different applications.
1. Modify lite_service.yml to add the following line:
app_server:
manager: true        # using dynamic app server (the default)
lsf:                 # if set, use lsf to invoke new servers; otherwise, new
server will be run on the same (local) machine
bsub: /path/to/bsub <args> # path to the executable bsub, together with
all necessary args
bkill: /path/to/bkill        # path to the executable bkill
For example:
lsf:
bsub: /grid/sfi/farm/bin/bsub -q vormetric -P EDI:MAIN:PV:QOSMT -W 120:00 -R
"OSREL==EE70 rusage[mem=110000]"
bkill: /grid/sfi/farm/bin/bkill
2. Stop and then start JedAI.
UNIX> jedai stop
UNIX> jedai status
3. On starting a new project, running jedai status will show that some new app servers have
started.
UNIX> jedai status
......
app_server_f697b018-b499-4653-a59a-7e50262c90c2 [5798]
http://<hostname>:5000/api/analytics/sessions/f697b018-b499-4653-a59a-
7e50262c90c2: active
Enabling HTTPS (TLS/SSL)
JedAI supports using HTTPS for encrypted communication with different services when provided
with both a private key and a public certificate signed by a Certificate Authority. If only a port number
is specified, JedAI will generate a self-signed certificate, but users will need to trust this certificate or
ignore warnings in their browsers and command-line utilities.
1. Modify lite_config.yml to include the tls configuration:
tls:
port: 5009
cert: /path/to/public/cert.pem
key: /path/to/private/key.pem
2. If JedAI is already running, stop and then start it again.
UNIX> jedai stop
UNIX> jedai status
Enabling LDAP Authentication
JedAI supports authentication with the Lightweight Directory Access Protocol (LDAP). Modify
lite_config.yml to include the LDAP configuration:
admin_portal:
port: <admin_port>
LDAP: true
env:
AUTH_LDAP_TLS_CACERTDIR: ""
AUTH_LDAP_TLS_CACERTFILE: ""
AUTH_LDAP_TLS_CERTFILE: ""
AUTH_LDAP_TLS_KEYFILE: ""
AUTH_LDAP_ALLOW_SELF_SIGNED: ""
AUTH_LDAP_TLS_DEMAND: ""
AUTH_LDAP_SERVER: "ldap://<LDAP_HOST>:<LDAP_PORT>"
AUTH_LDAP_BIND_USER: "<LDAP_BIND_USER>"
AUTH_LDAP_BIND_PASSWORD: "<LDAP_BIND_PASSWORD>"
AUTH_LDAP_SEARCH: "<LDAP_SEARCH>"
AUTH_LDAP_SEARCH_FILTER: ""
AUTH_LDAP_UID_FIELD: "<LDAP_UID_FIELD>"
AUTH_LDAP_FIRSTNAME_FIELD: "<LDAP_FIRSTNAME_FIELD>"
AUTH_LDAP_LASTNAME_FIELD: "<LDAP_LASTNAME_FIELD>"
AUTH_LDAP_EMAIL_FIELD: "<LDAP_EMAIL_FIELD>"
If there is no account with the same name as the LDAP account in the JedAI server database, a
local account with the same name and no password will be automatically created. The local
account password needs to be manually modified by the admin in the admin portal. If there is an
account with the same name as the LDAP account in the JedAI server database, the LDAP account
will be automatically associated with the local account.
Once LDAP authentication is enabled, you will see an LDAP login page on the main login interface.
If the LDAP login page does not display automatically after you enable it, you may need to
clear the cache.
Cluster Mode Installation
Prerequisites
Setting Up the Cluster
Prerequisites
Hardware Requirements
Number of nodes: Minimum 3
CPU cores: Minimum 8
Memory: Minimum 32 GB
Hard Disk: Minimum 10 GB. Using NFS as a shared file system to store your ingested data is
recommended.
Open ports for network access within organization. For example: 31100-31110. Ensure these
ports are not occupied by other processes.
If the ports are occupied and need to be changed, open those ports and modify the
corresponding port numbers in the configure file (config.yml).
Operating System
Centos == 7.4
Software Requirements
Docker > 19.03.15
Kubenetes > 1.22.4
LDAP Information
Sync the LDAP information into JedAI for authentication requirements. See the sample config.yml
file below for all required information.
Passwordless Access for Installing Users
1. On the original machine, create the Authentication SSH-Keygen keys:
UNIX> ssh-keygen -t rsa
2. Upload the SSH key to the target machine.
Use SSH from the source server and upload a newly generated public key (id_rsa.pub) to the
target server under the user’s .ssh directory and append the key to the file
named authorized_keys.
Alternatively, use the following command:
UNIX> ssh-copy-id user@target.machine
License Server Accessibility
JedAI uses the default Cadence license server environment. Please obtain your license server
information before you start installation.
Setting Up the Cluster
1. If you have python3 valid on the current machine, source it before installation as follows:
For bash:
UNIX> export PATH=<PYTHON_HOME>:$PATH
For csh:
UNIX> setenv PATH <PYTHON_HOME>:$PATH
2. Copy and unzip the tarball on the target machine as follows:
UNIX> tar -xvzf install.tar.gz
3. Modify the install folder and license in config.yml as shown below:
It is recommended to change install_path inside config.yml to an NFS location
on which you have read, write, and execute.
The length of the install_path should be less than 80 characters.
The CDS_LIC_FILE indicates the location of the Cadence license. For
example, 5280@sjflex1 indicates the license exists at server sjflex1, port 5280.
Make sure the license server is accessible from the current machine.
##config.yml
# the install_path should be a writable NFS path that can be accessed from all
machines of the cluster
install_path: /vols/dsg_hadoop04/mtest/jedai
# the disk where the install_path is located
disk: /vols/dsg_hadoop04
# place the primary node on the first line; Here, dsg-hnode01 is the primary
node and others are secondary nodes
hosts:
- dsg-hnode01.cadence.com   #primary node
- dsg-hnode02.cadence.com   #secondary nodes
- dsg-hnode03.cadence.com   #secondary nodes
- dsg-hnode04.cadence.com   #secondary nodes
- dsg-hnode05.cadence.com   #secondary nodes
ldap:
server: ldap://sjdpc-ldap-lb1.cadence.com
port: 389
base_dn: ou=people,o=cadence.com
user_login_attr: uid
bind_user_dn: cn=proxyagent,ou=profile,o=cadence.com
bind_user_password: proxy
uid_number_claim: uidNumber
gid_number_claim: gidNumber
install:
# username for installation, needs to be changed to the installation operator
before installation starts
user: username
privateKeyFile: /home/username/.ssh/id_rsa
license:
server: sjdpc-lic-lb1
port: 5280
nfs:
server: sjvclapa02-p6-hadoop-dpc
# registry_folder_path should be a writable NFS path, used as storage for
registry (localhost:32000)
registry_folder_path: /vols/dsg_hadoop04/mtest
# MozartLiteDataPV_path should be a writable NFS path, used to store the JedAI
service data
MozartLiteDataPV_path: /vols/dsg_hadoop04/k8s/jedai-data-jedai
# ExternalDataPV_path should be a writable NFS path, used to put data warehouse
and source data, if needed
ExternalDataPV_path: /vols/dsg_hadoop04
4. Run the install script:
UNIX> sh install.sh
This step may take some time. Please wait until the script finishes running.
5. Verify by visiting http://<primarynode_host>:31100 to access the UI.
Setting Up the Run-Time Environment
After the installation is complete, apply the following settings to set up the run-time environment:
1. Set the location of the JedAI library:
setenv CDNS_JEDAI_PATH $CDNS_INSTALL_PATH/tools.lnx86/jedAI/lib/64bit
2. Set the JedAI library in the shared library path:
setenv LD_LIBRARY_PATH $CDNS_INSTALL_PATH/tools.lnx86/jedAI/lib/64bit
Note: cdp_utility has a dependency on the JedAI library (libjedai.so). cdp_utility looks for
the JedAI library in CDNS_JEDAI_PATH. If CDNS_JEDAI_PATH is not set correctly, the utility checks
for the JedAI library in LD_LIBRARY_PATH. If both paths are not set up correctly, cdp_utility
reports an error.
3. Specify where the JedAI data is stored:
setenv CDNS_JEDAI_SERVER file://$HOME/vwdb_jedai
Related Information
License Requirements
Installation and Operation

---
## JedAI Web Server

Open the Web server URL recorded in the installation section on a Web browser.
As shown below, the home page of the Web server includes links to various JedAI components:
Dashboard - Superset; discussed in detail in the Building the Dashboard in Superset section
Flow server - Airflow; details are in the Pipeline and Workflow section
MLOps - mlflow; details are in the Machine Learning Operation Service (MLOps) section
Notebook - Jupyter notebook; Details are in the Notebook section
Catalog API servers - Details are in the Data Catalog section
App Server - Details are in the "Analytic Engine and App Server" section
Flow Api Server - Details are in the Pipeline and Workflow section
Login Page
Home Page
You can connect to only one JedAI instance from one browser instance. If you want to
connect to another JedAI instance, please log out first.

---
## JedAI Admin Panel

The Admin panel can be used to manage user accounts, review login accounts, update or delete
catalog entries, and review or stop running app sessions.
Admin Panel URL
Accessing Resource Usage and Session Status
Managing Users
Adding Users
Editing Users
Resetting User Password
Deleting Users
Editing User Roles
Managing Sessions
Managing Entities
Managing Datasets
Managing Index Documents
Managing Permissions
Adding a Permission Policy
Cloning a Permission Policy
Deleting a Permission Policy
Data Governance
JedAI Admin Commands
Admin Panel URL
To open the Admin panel, use the Admin panel URL that was recorded in the installation section
through a Web browser.
It will have the following format:
http://${jedai_server_host}:${jedai_server_port}/admin
Accessing Resource Usage and Session Status
On opening the Admin panel URL, the JedAI Admin landing page will appear as shown below.
Only admin users can use this page to track session status.
Managing Users
The admin can use the Security page of the JedAI Admin panel to manage users.
Adding Users
1. Click the Security tab on the top and select List Users from the drop-down list. The admin user
will have the ability to manager all users' roles and permissions here.
2. Click the "+" button to create a new user. Specify the new user's name, email, role, and
password.
In the User Name field, specify a valid UNIX or LDAP authentication ID.
In the Role field, select one or more appropriate roles from the given list.
If the user is expected to start jobs, such as launching a Cerebrus run, you must assign
the job_runner role, in addition to any other required roles, to that user.
3. Click the Save button.
Editing Users
1. Click the Edit ( ) button next to a user row to open the Edit User form. Here, the admin user
can edit the information and permission role for the selected user.
2. Make the required changes and click Save.
Resetting User Password
1. Click the Show Record (       ) button next to a user in the user list.
2. Click Reset Password to reset the user's password.
Deleting Users
Click the trash (   ) button next to a user row in the user list to remove that user.
Editing User Roles
Click the Security tab on the top and select List Roles from the drop-down list.
Here, an admin user can view and edit each role. Any edit will impact all users with that role.
Managing Sessions
The admin can use the Session page of the JedAI Admin panel to see the detailed session
information of each application.
To access the Session page, click the Session tab at the top.
The admin can stop any running session by clicking the red cross next to it. A warning message
appears as shown below:
Managing Entities
The admin can use the Catalog Entity page to track and manage dataset usage.
Managing Datasets
Click the Dataset option under Catalog Entity to view the summary of dataset usage, as shown
below.
You can use the filter for each column to analyze dataset information, as required.
Deleting Multiple Datasets
The Dataset page allows the selection and deletion of multiple datasets at a time:
1. Select the required datasets.
2. Click the Delete button below the table. A confirmation box pops up, as shown below.
3. Click the Confirm button in the confirmation box to complete the deletion.
Editing Dataset Metadata
Using the Dataset page of the Admin panel, data owners or the admin can update the metadata
associated with datasets.
To update metadata of the dataset:
1. Click the pencil button next to the dataset to be updated.
2. Update the metadata information for the dataset, as required, as shown below.
3. Click Update to submit the metadata changes.
Managing Index Documents
The Catalog Entity page can also be used to manage index documents.
Click the Index Document option under Catalog Entity to view the summary of index documents, as
shown below.
Editing Index Document Permission
1. Click the pencil button next to the index document to be updated.
2. Update the permission for the document, as required, as shown below.
3. Click Update to submit the metadata changes.
Managing Permissions
The Permission page of the Admin panel can be used to manage permission policies.
Click the Permission menu and choose the Permission Policy option. You can use the resulting
page to view the current status of a permission policy, add a new permission policy, and clone the
current policy.
Adding a Permission Policy
On the Permission page, click the "+" button next to Add Permission Policy and select the entity
type for which you want to apply permission.
This will take you to the policy config page. Here, you can add multiple glossary filters, look at the
filter results, and grant/revoke permission on multiple roles.
To support permission inheritance from an existing project, design, design version, or run tag, the
following conditions are supported:
Cloning a Permission Policy
To clone an existing policy, click the Clone (    ) button next to an existing policy.
This opens the policy settings page. You can modify the policy as needed, specify a new name, and
then click Create Policy to save it as a new policy.
Deleting a Permission Policy
You can select multiple permission policies and click the Delete button to delete them.
Deleting a permission policy does not mean revoking the permissions already granted under
that policy; you will need to create a policy to revoke permission on entities.
Creating a policy by hierarchy from project → design → design_version → run_tag is
recommended for Cerebrus AI studio. For example, if you specify run_tag, you should also
specify project, design, and design_version.
Data Governance
Overview
Role
Entity
Permission Type
Policy
Enable/Disable Authorization
Managing Dataset Permissions
Adding a Dataset Permission Policy
Cloning a Dataset Permission Policy
Deleting a Dataset Permission Policy
Managing the Cerebrus AI Studio Dashboard Permissions
Granting or Revoking Cerebrus AI Studio Dashboard Permissions
Managing Index Document Permissions
Adding an Index_doc Permission Policy
Cloning an Index Document Permission Policy
Deleting an Index Document Permission Policy
Overview
Use permission management in JedAI to manage the relationship between roles and entities.
Role
A role consists of a group of users.
System-default roles:
Admin: The Admin role has the highest authority in the system and can read, modify, and
delete all entities, by default.
User: By default, anyone with the User role can read, modify, and delete permissions for
entities that he or she created.
Public: From the JedAI perspective, the Public role has the same permissions as the
User role.
Self-defined roles:
An Admin user can add new roles using the Security menu in the JedAI Admin panel.
1. Click the Security menu on the top and select List Roles from the drop-down list.
2. Click the + symbol (Add a new record) in the List Roles section.
3. Specify a meaningful name for the role. Leaving the Permissions field blank is
equivalent to no permissions and would not influence JedAI usage.
Recommended Practice
For permission management, create self-defined roles with meaningful names.
Entity
An entity is the basic unit of permission management in JedAI. Currently, the entities with an
authorization mechanism are: dataset, monitor_dashboard, and index_doc.
Permission Type
Entity permissions are of the following four types, two of which can be modified within the JedAI
Admin panel.​
Read_only: Can only read data; cannot modify or delete. This permission can be modified
within the admin panel.
Read_write: Can read, modify, and delete data. This permission can be modified within the
admin panel.
Owner: Can read, modify and delete the entities that they own. The user who created an entity
is considered to be its owner and cannot be changed using the admin panel.
Admin: can read, modify and delete all entities by default.
Important
An entity without any permission is visible to everyone. Examples:
Anyone can see all history data as it has no permissions set.
If the Admin grants the Read_only permission to RoleA, it can be seen only by users
who belong to RoleA and cannot be seen by anyone anymore.
Policy
A permission policy is used to authorize a batch of entities. The permissions are granted to datasets
once the policy is created. After that, the policy cannot be modified.
If you need to add new permissions, you need to create a new policy.
Enable/Disable Authorization
Authorization is disabled by default. To enable authorization, update the authorization config
setting in lite_config.yml.
Here, true means authorization is enabled and false means authorization is disabled.
Managing Dataset Permissions
Admin users can create a permission policy to grant/revoke permission to roles on a set of datasets.
Adding a Dataset Permission Policy
In the JedAI Admin panel:
1. Click the Permission menu and select Permission Policy.
2. Click the + symbol next to Add Permission Policy.
This opens the page shown below.
Using the page, you can:
Add multiple glossary conditions to associate specific datasets to different policies.
Use the Get Filter Results button to preview dataset selections.
Use the available add and remove buttons to refine dataset selections.
Choose Grant or Revoke permission roles on the selected datasets.
3. Specify a policy name and then click Create Policy.
Cloning a Dataset Permission Policy
To clone an existing dataset policy, click the Clone button, as shown below:
In the resulting page, you will have all the permission settings of the cloned policy. You can edit the
glossaries filters, reselect datasets, and update the permission roles, then create a new policy with a
new policy name.
Deleting a Dataset Permission Policy
An admin user can select multiple policies and then click Delete.
Managing the Cerebrus AI Studio Dashboard Permissions
Granting or Revoking Cerebrus AI Studio Dashboard Permissions
In the JedAI Admin panel:
Open the Permission menu and select Other Permission to check permissions of all entities in the
Cerebrus AI Studio dashboard.
Click the Edit symbol next to the dashboard for which you want to change permissions.
In the resulting page, grant or revoke Read Only and Read and Write permissions for the required
roles.
Important
In the Cerebrus AI Studio UI, the Read Only permission enables viewing of permitted
Cerebrus AI Studio dashboards, and Read and Write permission enables viewing and
deletion of permitted Cerebrus AI Studio dashboards.
Note that a Cerebrus AI Studio dashboard without any specified permission, such as
test_dashboard1 shown below, is visible to every one.
Suppose a current non-admin user belongs to the roleAIS role, and there are three Cerebrus AI
Studio dashboards with permissions as shown above. Then, a current non-admin user would only
see test_dashboard1 and test_dashboard2 in his or her Cerebrus AI Studio UI dashboard list.
Managing Index Document Permissions
Managing index document permissions is similar to managing dataset permissions. Admin users
can create a permission policy to grant or revoke permission to roles on a set of index documents.
Adding an Index_doc Permission Policy
1. Click the + symbol next to Add Permission Policy.
2. In the resulting page, select index_doc from the Select Entity Type drop-down to create a
policy for a set of index documents.
3. Add a glossary filter for the index_doc entity. An example is shown below.
4. Specify a policy name and then click Create Policy. The created policy is listed under
Permission Policy as shown below:
Cloning an Index Document Permission Policy
To clone an existing index document policy, click the Clone button, as shown below:
In the resulting page, you can edit the glossaries filters, reselect datasets, and update the
permission roles, then create a new policy with a new policy name.
Deleting an Index Document Permission Policy
An admin user can select multiple policies and then click Delete.
JedAI Admin Commands
To use the JedAI admin related commands, you need to first set up the correct environment by
running the following command:
bash:
UNIX> source $JEDAI_INSTALL_PATH/setup.sh
csh:
UNIX> source $JEDAI_INSTALL_PATH/setup.csh
create-user
create-role
add-role-to-user
reset_admin_password
create-user
The create-user command is used to add new users to the JedAI server.
admin-password ADMIN_PASSWORD]
add user to JED AI platform
optional arguments:
password for Admin user
create-role
The create-role command is used to add new roles to the JedAI server.
update user in JedAI platform
optional arguments:
password for Admin user
add-role-to-user
The add-role-to-user command is used to add existing users to existing roles on the JedAI server.
ROLE]
update user in JedAI platform
optional arguments:
password for Admin user
reset_admin_password
The reset_admin_password command is used to reset the admin password.
UNIX> jedai reset_admin_password

---
## JedAI Web Applications

Various Web apps are delivered along with the JedAI platform. These are real applications of data analytics, and can be treated as
sample Web app implementations that use the underlying building block of the JedAI platform, including Catalog, Analytic Engine,
Notebook, and so on. In later sections, you can use these components to build your own customized Web apps.
General Flow of Apps
To run an app, you need to start by choosing the right dataset(s) from the Data Catalog page and creating a project using the chosen
dataset(s). Once the project is created, you can run the project by clicking the project name. The detailed steps are as follows:
1. Click the Data Catalog page. You will see the list of datasets that have been ingested, as shown below:
2. From the Apps column in the dataset list, you will know whether the dataset can be run on the desired app. If the intended app is
not in the Apps list for the dataset, you can add it by clicking the dataset and then clicking the Associate App button.
Multiple filter conditions are supported. You can filter datasets by adding filter conditions on columns and then clicking Apply to get
the target datasets. This is useful when the number of datasets is high as you can quickly locate the datasets you require and
proceed with associating target datasets with apps or selecting datasets for creating a project.
3. To create a project, select the required dataset(s) from the list, choose an application, and then give a project name.
Sample Ratio: This is an optional parameter that you can use to avoid request timeouts on large datasets. By default, it will
use 100% of the available data to run the application. However, you can specify less data to sample (for example, 50%) to
reduce the computation time.
Engine: Specifies the calculation engine. The default engine is pandas. You can also select spark as the calculation engine.
If you select the spark engine, you can also specify Spark Mode and change Spark Options.
You can specify cluster in Spark Mode only if you have enabled the spark cluster during installation, as specified in
Single-node Mode Installation.
4. Once the project is created, choose the project from Projects page on the left panel and click the project you created. The project
will start running.
5. In the meantime, on the left panel, the project page link is added. By clicking that link, you can see the running (or still running)
result for the project.
6. Click the "+" button on the top right corner of the APP name (for example, Timing Matrix) to get the dataset information for this
project.
The apps included with the JedAI platform are:
Budget Analyzer App
Buffer Tree App
Clock Tree App
Conformal App
Congestion Analyzer App
Heat Map App
Parameter Analyzer App
PPA Compare App
Silicon Sight App
Timing Matrix App
Budget Analyzer App
Introduction
Datasets
Specifying Parameters
Result
Database Comparison
Introduction
The Budget Analyzer app can be used for the following:
Analyze the IO constraints for different partitions, where applicable:
Trace all the inter-partition paths and check if the external delay or input delay is good for the path.
Compare the same path at top and in partitions:
Check a path at the top level before partition.
Check the same path at the top level after partition with assembling.
Check the same path in different partitions with IO constraints.
Datasets
At least three datasets are required: one budget dataset, one reference dataset, and one or more partition datasets.
Important
You must add a tag for each type of dataset (budget/reference/partition) in the Catalog page.
The relevant extract from a sample configuration file for the write-dataset command is shown below:
setup: true
hold: false
libobjs: true
dbobjs: true
path: true
nworst: 1
max_paths: 100000
max_slack: 2
hpin: true
blocks:
SOC:
per_partition: true
stages:
partition:
comment: budget
alias: floorplan
postroute:
comment: reference
alias: postroute
BLOCK1:
io_only: true
stages:
postroute:
alias: postroute
comment: partition
BLOCK2:
io_only: true
stages:
postroute:
alias: postroute
comment: partition
Specifying Parameters
1. Choose the required values for all the parameters in the Partitions database selector:
2. Click the Compare databases button when done.
The database comparison is generated and displayed, as shown in the Result section below.
Result
Database Comparison
You can filter rows and columns using the Filter Rows text box and the       button.
A chunk of 100 paths is fetched each time. If you want to see more paths, click Fetch more data from the server.
Click any row in the table to view its details in the Path details pop-up.
In the Delays section of Path Details:
The left hand side shows the timing results from the point of view of the assembled designs (budget and reference tags).
Here, Golden represents results from datasets with the budget tag.
The right hand side shows the timing results from the partition point of view (partition tag).
The arrival time of the clock and data endpoints are depicted by the triangle shapes. The color-coding of the shapes is as
depicted in the legend.
The amount of time spent in each partition is shown by the solid bar graphic.
The budget applied for each port is shown by the shaded bar graphic.
Buffer Tree App
Introduction
The Buffer Tree app can be used to:
Check the buffer instance placement quality throughout the flow.
Calculate the basic attributes of a buffer tree — buffer count, sink count, distance, and wirelength.
Calculate the wasted wirelength by the difference between the ideal Steiner tree length and the actual length after inserting
the buffers.
Calculate the optimality of each buffer tree.
Check each buffer tree's physical and logical structure.
Check the buffered Q-SI paths.
Check their path structure and delay.
Check their logical structure.
Usage
1. Specify what you want to analyze by choosing either Buffer_tree or Scan_chain.
2. Click APPLY.
Result
Buffer tree optimality histogram
The smaller the optimality, the better the quality.
Buffer tree summary table
Ideal length is typically 1, as shown above.
Single buffer tree visualization
Physical and logical level
Level color is shown in the order of white, blue, and yellow.
The root instance is displayed in green and the buffer instances in red.
Q-SI path summary table and distance histogram
Click each row to get its logical path.
The Q register is displayed in green and the SI register in red.
Clock Tree App
Introduction
The Clock Tree Debugger (CTD) app can be used to:
Check the clock instance placement quality before and after the CTS stage.
The longest and shortest distance leaf of each clock tree from the root port.
The skew group's skew on the whole clock tree from the root port.
Check each stage level all arcs statistic result.
Check each root-leaf path detoured point and sink count.
Check each clock instance timing, including launching and capturing, which can be used for useful skew to fix violations.
Check the clock path quality of violated paths from the Silicon Sight app.
Track results across the flow or between different runs.
A progress bar displays the percentage of calculations completed. This helps you estimate the time remaining for the checks to be
completed.
Specifying Parameters
Analysis view
Detour Threshold: Only the path over the Manhattan distance from root to leaf, and the path that has real distance divided by
Manhattan distance over the threshold will be reported.
Result
Skew summary
The longest and shortest distance leaf of each clock tree from the root port.
The skew group's skew on the whole clock tree from the root port.
Level summary
Detoured path
Skew suggestions for improving skew
All clock instance timing
1. Loop the timing slack on all clock tree instances, such as A, on both the capture data path (Path1) and the launching data
path (Path2).
2. If the instance is close to the root, both Capture Tns and Launch Tns are bad. Such a point cannot be used for clock skew.
3. Filter the clock instances with Launch Tns less than 0 and Capture Wns greater than 0. These clock instances are close to
the leaf.
4. If Path1 is less than 0 and Path2 is greater than 0, A can be slower. Otherwise, if Path1 is greater than 0 and Path2 is less
than 0, A should be faster.
The table shows that CTS_ccl_a_buf_00047/Z should be chosen for the skew benefit of -1.68ns tns, and the margin that can be
used is 2.53ns.
Violated path from the Silicon Sight app.
All the paths saved from Silicon Sight for the Clocks category will be shown here for clock path debug.
Click each path:
Save violated paths in Silicon Sight: In the Silicon Sight app, you can click a category and click Save.
If the paths for the Clocks category are saved here, they will show up in the Clock Tree app.
Clock Tree Widget
Shows the clock tree by depth.
​
Clicking a root will show all the node values.
​
Supports four types of attributes.
​
Place the cursor on a node to see the node attribute table.​
Click a blue leaf node to see the launch path.
​
Click a red leaf node to see the capture path.
​
Supports 20%~500% zoom in and zoom out.​
Right click a node to cancel the highlight.​
Conformal App
Introduction
Requirements
Hardware Requirements
Software Requirements
Other Requirements
Saving and Ingesting LEC Data for JedAI
From LEC
Setting Up the LEC Dofile
Executing LEC for the Modified Dofile
Access the Dashboard of the JedAI Project
From JedAI
Result
Summary Page
Partition Dashboard
Non-equivalent Module(s) Page
Abort Module(s) Page
Comparing Datasets
Dataset Comparison
FV Comparison
Modules Comparison
All Commands Comparison
Using the Live Update Feature
Enabling Live Updates
Viewing Live Updates
Introduction
Use the JedAI Conformal app to:
Deliver FF Power Performance Area (PPA) targets.
Make better Engineering Change Orders (ECOs), speed up Logical Equivalence Checking (LEC), and avoid aborts.
Debug intuitively.
The Conformal ® Logical Equivalence Checker (LEC) and JedAI combination provides improved debug answers and insights.
Use Conformal LEC to write out data in each LEC run and then use JedAI Conformal app to analyze the data and present diagnosis.
The Conformal app:
Allows you to capture custom metrics
Enables you to compare metrics across different runs with RTL changes
Generates future-run scripts to optimize the LEC runs
Requirements
Hardware Requirements
CPU cores: 4 minimum
Memory: 4GB minimum
Hard Disk: 40GB minimum. Note that this requirement is only for system artifacts. A large disk is recommended for storing your
ingested data.
The disk requirement will vary depending on the design.
Open ports for network access within the organization, such as 5000-5020.
Ensure these ports are not occupied by other processes. If the ports are occupied and need to be changed, open those ports and
modify the corresponding port numbers in the lite_config.yml configuration file.
Software Requirements
Conformal LEC 24.2 or later
JedAI 25.10 or later
Operating System
Centos (RHEL): 8.4
The software mentioned below are installed as part of the installation:
Python 3.9.6
Npm 6.14.11
Nginx 1.20.0
Other software
GCC 4.8.5 or above
libstdc++ 4.8.5 or above
tar 1.26 or above
Other Requirements
User Permission Requirements:
A valid Linux non-root user
License Server Accessibility:
JedAI uses the default Cadence license server environment. Make sure to obtain your license server information before you
start the installation.
Saving and Ingesting LEC Data for JedAI
Before generating and ingesting LEC data for JedAI, you must have:
Conformal LEC 25.1 or later with the Conformal_AI_Basic (-ai_basic) license
A JedAI server, installed and running
From LEC
To save data from LEC and ingest in JedAI:
1. Set up the LEC dofile.
2. Execute Conformal LEC for the modified dofile.
3. Access the Dashboard of the JedAI project.
Setting Up the LEC Dofile
1. Add the following set_data_logging commands at the beginning of the existing LEC dofile, just after the set_log_file command
and before the existing dofile commands:
set_log_file cfm_jedai.log -replace
set_data_logging –enable
set_data_logging –jedai_url <jedai_server_url>
set_data_logging –create_jedai_project <jedai_project_name>
<LEC dofile commands>
Here:
–jedai_url <jedai_server_url> is used to specify a JedAI server for the LEC run. LEC can automatically ingest the needed
dataset to the specified JedAI server. You can get the URL from the JedAI server installation.
–create_jedai_project <jedai_project_name> is used to associate the dataset to a JedAI project. Note that this is different
to the -project option, which changes the dataset project tag.
2. Add the following set_data_logging command at the end of the existing LEC dofile, just before exit:
set_data_logging –ingest_jedai_data
Here's a sample dofile:
set_log_file cfm_jedai.log -replace
set_data_logging –enable
set_data_logging –jedai_url <jedai_server_url>
set_data_logging –create_jedai_project <jedai_project_name>
read_design golden.v –golden
read_design revised.v –revised
set_system_mode lec
add_compared_points –all
compare
set_data_logging –ingest_jedai_data
Executing LEC for the Modified Dofile
Execute LEC with the modified dofile by using the following command:
lec -nogui -ai_eq -dofile dofile_name
LEC ingests the complete dataset to the JedAI project specified in the dofile.
Each JedAI dataset has tag values associated with it. LEC automatically fills in the tag values.
JedAI increments the dataset versions if the following tag values are the same between LEC runs. This is important for run-to-run
comparisons in the Conformal app.
You can specify the field values using following set_data_logging options:
-PRoject, -DEsign, -DESIGN_Version, -RUn_tag, -FLow_phase, -SCenario
The tag of the ingested dataset is displayed in Catalog of JedAI.
Access the Dashboard of the JedAI Project
Use the Dashboard URL link in the log file to directly view the Dashboard or Summary page of the specified JedAI project.
From JedAI
To ingest LEC data into JedAI server:
1. Source the JedAI setup file:
source $JEDAI_INSTALL_DIR/setup.csh
2. Use the ingest-dataset command to ingest LEC data into JedAI:
<file_list>
Example
/home/user/demo/cfm_jedai.tar
Here:
top will be the name shown in the Design column in the JedAI Catalog table.
LEC will be the name shown in the Phase column in the JedAI Catalog table. This name can be any identifier that will help you
organize your view.
After the LEC data has been ingested, follow the steps mentioned in the General Flow of Apps section in JedAI Web Applications to
associate the LEC dataset to the Conformal app and create a Conformal project.
Result
Click the required Conformal project in the Projects list.
This opens the Summary page of the selected Conformal project.
Summary Page
The Summary page:
Displays the LEC run results summary, issue summary, and runtime histogram for the associated LEC cases.
Lists the LEC cases associated with the project in a table.
Click a link under the Partition column to go to the corresponding Partition Dashboard page.
Click a link under the Result column to go to the respective NEQ Modules or Abort Diagnosis page.
The Issue column identifies the potential issues for the LEC run. The issue summary serves as an early warning or provides
next step guidance on diagnosing the LEC run result. Click on an issue link to pop up a window with more information about
the issue, including the issue description, criteria to trigger, and potential impact.
Partition Dashboard
To open the Partition dashboard of an LEC run, click the corresponding link under the Partition column in the LEC Case(s) section of the
Summary page.
The Partition dashboard:
Displays the overall information related to the LEC run. Click on links and hover over objects to get more detailed information about
them.
Displays the dataset version information related to the LEC run in a tabular format. If multiple dataset versions are available, the
table shows information about each of them.
Enables you to switch between available dataset versions easily on the dashboard. Select the required version from the Current
version drop-down.
JedAI updates the dashboard information to the corresponding dataset version.
Displays the overall module comparison results in the Module Result Count section. Click on any link to get more information
about the related module.
Displays additional tables, depending on the LEC run. For example, the Partition dashboard could show an FV Qualification
Summary table, as shown below.
Click on any link to view more detailed information.
Non-equivalent Module(s) Page
To open the Non-equivalent (NEQ) Module(s) page of an LEC run, click the corresponding non-equivalent link under the Result column
in the LEC Case(s) section of the Summary page.
The Non-equivalent Module(s) page displays the possible root causes associated with the NEQ points. You can click links for more
detailed information.
Click the Diagnose link to open the Diagnose Non-equivalent page. The Diagnose Non-equivalent page:
Shows the NEQ key points and root causes. Click the Rootcause - > Count link to view detailed information.
Shows information about the sensitivity cone for the NEQ point. The sensitivity cone refers to the refined logic cone where the
NEQ likely exists.
The page includes information about RTL and Modeling messages in the sensitivity cone.
Shows information about the critical path for the NEQ point. The critical path refers to the path from a non-corresponding
support to the NEQ diagnosis point that causes the NEQ.
Abort Module(s) Page
To open the Abort Module(s) page of an LEC run, click the corresponding abort link under the Result column in the LEC Case(s) section
of the Summary page.
The Abort Module(s) page displays a summary of possible data path (DP) and MDP failures and root causes for aborts.
Click a link in the Failure DP or Failure MDP column to view an analysis of the DPs/MDPs with low quality results.
Click the View link in the Logfile column to open the Logfile View page showing a log snippet related to the Abort points.
Click a link in the Abort Group(s) column to open a sub-window that categorizes the abort points into different groups for diagnosis.
Click the Diagnosis link in the row for an abort group to open its diagnosis page.
The upper pane of the Diagnose Abort Group page shows abort key points and their root causes.
Click on the + symbol to the left of a root cause to view more information. The expanded information shows the RTL file
where the issue occurred and related message. Hover over the RTL filename to view the corresponding RTL snippet.
The lower pane of the Diagnose Abort Group page displays the Critical Path table. The critical path shows the path that
poses verification challenges for LEC.
Inspecting the path allows you to confirm the root causes identified.
Click on the Detail links to bring up the corresponding critical paths. This shows an example on a critical path on the
Golden design.
Comparing Datasets
JedAI can store different dataset version information for cases. The different dataset versions can be compared to view run-to-run (R2R)
differences.
Click the Dataset Compare tab to view different compare options:
Dataset Comparison
1. Select the Dataset Compare option from the menu.
2. Copy the dataset UUID from the Dashboard page and paste in the Please input the dataset UUID field.
By default, the current dataset version is displayed on both the left and right sides when you paste the dataset UUID.
3. Switch to the required dataset versions for comparison by selecting them from the version drop-down lists.
The differences between the selected dataset versions are then displayed side-by-side.
Click any link to view more detailed information.
Click the Run R2R Analysis button to view or change analysis settings and rerun analysis.
Click Check Root Cause Analysis to view details.
FV Comparison
Select FV Comparison from the menu.
The FV Comparison page shows the FV qualification results between two different datasets versions.
Modules Comparison
Select Modules Comparison from the menu.
The Modules Comparison page shows the module comparison results between two dataset versions. If R2R analysis has been
performed, you can view more detailed comparison analysis for a module by clicking the Analysis link of that module.
All Commands Comparison
Select All Commands Comparison from the menu.
The All Commands Comparison page highlights the different LEC commands used between the dataset versions being compared.
Using the Live Update Feature
Conformal LEC can automatically ingest datasets to the JedAI server with the live update feature. You can monitor an LEC run using the
JedAI dashboard. This enables you to get detailed data on an ongoing LEC run and take preventive steps by helping you diagnose and
categorize issues early.
Enabling Live Updates
To enable the live update feature, use the set_data_logging -live_update command.
By default, LEC will update and ingest dataset to the JedAI server in 600-second intervals. To change the interval period, use the
following command:
set_data_logging -ingest_interval value_in_seconds
Here's a sample dofile for enabling live updates:
<start_of_LEC_dofile>
set_data_logging –enable
set_data_logging –live_update
set_data_logging –ingest_interval 1800 // Changing to 30-min ingest interval
set_data_logging –jedai_url <jedai_server_URL>
set_data_logging –create_jedai_project <project_name>
<rest_of_LEC_dofile>
set_data_logging –ingest_jedai_data
Viewing Live Updates
To view the JedAI Live dashboard page of an LEC case, click the corresponding view link in the live column of the LEC Case(s) table:
The JedAI Live dashboard page updates automatically when new data is ingested:
The top section indicates the current stage of the LEC run.
The <module> compare points status section displays the status and count for each type. Hover over any bar to get the count and
click it to get the compare point list for that type.
The Issues section lists the early issue categorizations. Click pn an issue to get more information, such as its description, criteria,
and potential impact.
The Module Progress section depicts the progress of the hier comparison. Click on any module name in the list to get information
about its submodules.
The Summary section gives high-level run information:
After a run is complete, the stage at the top changes to Finished. Click the highlighted link to go to the partition's dashboard.
Congestion Analyzer App
Introduction
Launching the App
Congestion Hotspot Algorithms
Algorithms for the Congestion Tab
Algorithms for the All Categories Tab
Configuring Hotspot Calculations
Viewing and Analyzing Results
Comparing Multiple Datasets
Introduction
The Congestion Analyzer app aims to uncover congestion-related issues and deep dive into their characteristics and details. This
includes:
Identifying congestion hotspots (3D on metal layers) and ranking their criticality based on total congestion and area.
Extracting comprehensive attributes/details for each hotspot.
Uncovering the root cause for a congestion hotspot and providing suggestions. This leads to quicker fixes and co-optimization.
Launching the App
1. Assign the required design datasets to the Congestion Analyzer app and create a new Congestion Analyzer project. For more
details, see General Flow of Apps in JedAI Web Applications.
2. Start the new Congestion Analyzer project from the Projects page. As the app starts running, it will perform all the necessary
analysis based on the selected datasets and visualize the results on the JedAI front-end interactively. A progress bar will appear to
indicate the current calculation progress. After it completes, the app will be launched as shown below:
3. Click the + symbol next to the project name to view the project information in a pop-up window.
Congestion Hotspot Algorithms
By default, two sets of algorithms are used in the app – one for the congestion tab and the other for the all categories tab.
Algorithms for the Congestion Tab
For the results shown in the congestion tab, the app actually follows the clustering idea of Innovus, namely grouping the congestions in
the vicinity and ranking them by total overflow and hotspot area.
Innovus Congestion Table
Congestion Analyzer Hotspot Summary Table
The left side displays the statistic summary, which is collected based on the hotspot area and key indicators. This helps you identify
easily the layers that are dominant in terms of congestion. Here, the x-axis displays the sum of Gcell area or overflow and the y-axis
displays the hotspot count.
The table on the right shows the extracted hotspots, ranked by the total overflow and hotspot area. Here:
Cnt Gcells: Represents the Gcell count for which the overflow is greater than 0.
Overflow: Represents the sum of the overflow value of all the Gcells.
Layer (<count>): Aggregates the nearest Gcell to hotspot bbox count.
llx, lly, urx, and ury: Specify the bbox shape.
The app result is slightly different from the Innovus result because of differences in the clustering algorithm and filter method used.
In the right-side table, click on any hotspot to visualize it on the actual design shown on a PDGUI and check its key indicators in the
Detail Information table. For more information, see Viewing and Analyzing Results.
Algorithms for the All Categories Tab
The all categories tab follows a different set of algorithms to collect hotspots. It follows Small/Medium window aggregation, as shown
below.
Hotspots are collected based on user-defined criteria and severities. See examples below:
This algorithm applies not only to congestion, but also to other hotpots, such as cell_density, pin_count, hold_timing and setup_timing.
For more information, see Viewing and Analyzing Results.
Configuring Hotspot Calculations
You can configure how hotspots are calculated by clicking                      . This opens a configuration box, as shown below.
By default, there are two categories, Danger and Caution. If the severity toggle is turned on, only Danger hotspots will be shown.
Aggregation of the Medium box uses 10*10 small boxes with a half-sized stepping (5*5 small boxes), by default.
On each heatmap hotspot, such as congestion, method shows the aggregation used to calculate indicators in the medium box as
opposed to the small boxes. You can modify the map grid for the small box. The base value is the default row_height of the design.
Therefore, map grid 5 means 5*row_height. Modifying the default map grid for congestion heatmap is disabled for now because it
utilizes Gcell by default.
Each severity threshold has a range to indicate hotpots. The meaning of each number is explained below:
congestion: Value of total overflow
cell_density: Actual cell density
pin_count: The count of pins
hold_timing/setup_timing: The averaging negative slacks (TNS/FEP) normalized to capturing clock
Clicking Apply after making Config changes will kick-off hotspot calculation based on the new configuration.
Taking cell_density, for example:
Danger → Small: 0.98~1; This means in a small Gcell bbox, if the density is over 0.98, it is dangerous.
Danger → Medium: 0.95~1; This means in a medium Gcell bbox, if the density is over 0.95, it is dangerous. A medium bbox is
equal to a 10x10 small bbox.
Caution → Small: 0.95~0.98; This means in a small Gcell bbox, if the density is over 0.95, take caution.
Caution → Medium: 0.90~0.95; This means in a medium Gcell bbox, if the density is over 0.9, take caution.
Viewing and Analyzing Results
1. Click any hotspot in the table on the top pane to visualize it on the actual design shown in PDGUI and check its key indicators in
the Detail Information table, as shown below.
By default, all heatmaps, such as congestion, cell_density, pin_count, and timing, are not shown on the GUI. This is for
performance considerations because heatmap data may be genuinely large (gzip compression and sparse matrix are already
implemented). You need to retrieve the heatmap you require once to have it included. For example, to see congestion in
layer M2, select congestion:M2 from the Type drop-down and click Submit:
On successful addition, the following message is displayed:
Congestion Analyzer PDGUI supports congestion display in two formats - RED and RGB. Use the Congestion Color toggle
to switch between the two formats.
The panel on the right shows the visibility of various objects in the design in PDGUI.
The key indicators of the highlighted hotspot are shown in the Detail Information table.
2. Click a link in the Suggestion column to see Tcl suggestions for improvement.
3. Click Clear Hotspot Selection to remove the hotspot selections.
4. Click the all categories tab to view other heatmap categories.
By default, Congestion Analyzer will only compute the hotspots related to congestion and cell_density first due to
performance considerations. You may click each of the remaining tabs to calculate the corresponding heatmap-related
hotspots.
5. Use the Save button at the top to save the congestion-related results as metrics for correlation with other applications.
The hotspots are saved and the results can be displayed on the JedAI dashboard.
Comparing Multiple Datasets
Congestion Analyzer supports comparison of multiple datasets.
Heat Map App
Datasets
Only one dataset is supported for one Heatmap project.
Result
ViaCountMap, PinCountMap, CongestionMap, and CellDensityMap are supported.
For CongestionMap, you need to choose a layer.
Parameter Analyzer App
Introduction
Result
Orthogonality Check Spreadsheet
Parameter Tables
Parameter Graphs
Design Structure Matrix
Introduction
The Parameter Analyzer app can read one or more design RTL source code files and:
Automatically generate the orthogonality check spreadsheet, which supports modification and download.
Output a list of tables, where each table references a set of interacting parameters.
View parameter interaction and system complexity in the form of a graph and the Design Structure Matrix (DSM), respectively.
Limitation
The Parameter Analyzer does not support System Verilog yet.
Result
Orthogonality Check Spreadsheet
This includes two tabs:
1. Orthogonality circuit-diff: Displays all the possible parameter combinations for each parameter from the RTL code aspect to catch
the differences from design specification.
2. Orthogonality summary: Lists the parameter interactions extracted from the design specifications. By default, the orthogonality
summary is the same as the orthogonality circuit-diff. Users can modify it based on their design specs.
Parameter Tables
Parameter tables specify the interacting parameter value combinations and the corresponding source code location. For example, in the
screenshot below, line number 27536,146403,34488,145847 are the locations where the value 1 of the second parameter, LCH, is
declared/instantiated/referenced/.
Parameter Graphs
A Parameter-Parameter graph represents the relationships between parameters.
The graph components are described below:
Nodes: Correspond to a parameter or a group of parameters.
Edges: Correspond to the direction of influence. See Parameter Influence Rules for details.
Edge Labels: Represent either a condition under which the influence occurs or a function name.
A Parameter-Signal graph shows the parameters used to determine the signal width.
Parameter Influence Rules
1. Parameter P is said to be “used” if:
P is referenced in an if or case statement or a for loop.
P is declared in an instantiated module.
P is passed in as a parameter in a module instantiation.
2. Parameter P1 influences parameter P2 if:
P2 is “used” in a generate-if block where P1 is referenced in the condition.
P2 is “used” in a generate-for block where P1 is referenced in the for loop header.
P2 is “used” in a generate-case block where P1 is referenced in the case statement.
P2 is an output of a function in which P1 is passed in as an input.
3. Parameter P1 and parameter P2 are grouped if:
P1 and P2 are referred in the same condition in an if statement.
P1 and P2 are referred in the same set of if/else-if conditions.
P1 and P2 are referred to in the same for loop header.
P1 and P2 are referred to in the same case statement.
Design Structure Matrix
Like the Orthogonality Check spreadsheet for parameters, the Design Structure Matrix (DSM) also depicts the interaction between
parameters.
Examining any row in the matrix reveals all the parameters that are influenced by the parameter in that row.
Looking down any column of the matrix shows all the parent parameters to the parameter in that column. That is, it shows all the
parameters that influence the parameter in that column.
The parameters that interact a lot with each other are displayed adjacent to each other and in the same color.
PPA Compare App
Datasets
Specifying Parameters
Result
Timing Summary
Slack Comparison
Area and MCR Summary
Area Comparison
Power Summary
Power Comparison
Length Summary
Length Comparison
Datasets
At least two datasets are supported with the same design name.
Specifying Parameters
1. Choose a view (Setup or Hold).
2. Choose a base dataset (one of the selected datasets).
3. Choose the hinst.
a. By default, the top hinst is chosen. You can change the hinst if required. Click + to open the modal window for hinsts.
b. In the hinsts modal, click + or - in the table to expand or collapse the hinsts.
c. Click a cell under the Hinst Name to select it.
4. Click APPLY to get a comparison.
Result
The resulting display is divided into four parts – Timing Summary, Area & MCR Summary, Power Summary, and Length Summary.
In VLSI design, MCR stands for Minimum Covering Rectangle (or Minimum Chip Rectangle).
For each widget, you can click     to get a detailed comparative result between the specified base and compare datasets.
Timing Summary
Displays the Worst Negative Slack (WNS), Total Negative Slack (TNS), and Failure Endpoints (FEP) for the selected datasets.
Click    at the top-right corner of the Timing Summary widget to view the Overall Summary Table, which displays the timing, area, and
power summary for the selected datasets. The table is sorted by flow phase.
You can use the Columns Filter button at the top-right corner to customize the columns that are displayed in the summary table.
Slack Comparison
Click      at the top-right corner of the Timing Distribution for Pins widget to view slack comparison.
The Slack Compare page:
Shows path endpoint changes. For each path, only the matching endpoint is displayed currently.
Enables you to filter by slack. Only the paths with slack less than the specified threshold are analyzed. While sorting by slack, only
the paths with specified slack are anlyzed.
Supports filtering of paths and calculation of each cell type count for each path if a pattern configuration is provided. For example:
Filter1: 'path_group_name="reg2reg" and slack<1 and `169H_cnt`>=0'
Filter2: 'pin = "pin:dsp_top/i_dsp/op_div_reg[3]/D" and
start_point="pin:dsp_top/i_down_counter/counter_value_reg[0]/CK"'
Pattern Config: vt_class: ["ULVT", "LVT", "UHVT", "HVT"]
Cell_type: ["AOI", "OAI", "BUF", "INV"]
Total 30+ columns can be selected for comparison. Use the Columns Filter (        ) button at the top-right corner to customize
the columns that are displayed in the Pattern Distribution table.
Click a row in the table to view the path detail, pin by pin.
Displays the slack contribution by object – net, inst, or base_pin. For example, the following screen shows the slack contribution by
net:
Area and MCR Summary
Displays the area and Minimum Covering Rectangle (MCR) summary for the selected datasets.
Area Comparison
Click      at the top-right corner of the Area Distribution for Instances widget to view the area comparison.
The Area Compare page:
Provides instance count comparison.
Supports different base cell class statistics. For example:
vt_class: ["HVT", "LVT", "ULVT", "UHVT"]
driver_strength: ["X1", "X2", "X4", "X8"]
pn_type: ["PNNP", "PNPN", "PPNN"]
MBFF: ["MB2", "MB4", "MB6", "MB8", "SDF"]
hybrid_row: ["169H", "286H", "117H"]
EEQ: ["PGQB", "PGQA"]
Enables you to check power or area distribution of cell or VT_type. The pattern list can be ["BUF", "INV", "SDF", "MS2",
"MS4", "TAP", "CLKG"] or any pattern you want to check.
If want to check buffer VT, the pattern is ["BUFF\\S+ULVT", ""BUFF\\S+UHVT", "BUFF\\S+LVT", "BUFF\\S+HVT"]. You can
use ^\\S+$ to regexp any base_cell.
Enables you to get clock gating summary. For example, you can check power or area for ["ICG","CKBD", "CKND"] as follows:
Enables you to focus on only those instances that are on the critical path.
Enables you to check for row utilization. To do so, turn on the Row Utils toggle and click Apply.
Enables you to check the instance movement by dataset:
Supports dead area and EEQ swap checks for 2 and 3nm designs only. EEQ swap is supported only for the base dataset.
Enables you to check the library for placement by analyzing the standard cell pin accessibility and cell-to-cell available spacing.
Only the base cells with a legal average pass ratio less than or equal to the threshold are analyzed.
Power Summary
Displays the power summary for the selected datasets.
Power Comparison
By default, dynamic power distribution is shown. You can use the drop-down to view internal, leakage, switching, or total power
distribution .
Click       at the top-right corner of the Power Distribution for Instances widget to view the power comparison.
The Power Compare page:
Shows power change distribution and total power change for instances.
Supports design level power analysis. For average power for the specified base_cell, you can specify a pattern, such as
base_cell:(\S+)(D\d+)\S+ or base_cell:BUF(\S+)(D\d+)\S+BWP in the Base Cell Suggestion section.
Here, the first value in brackets is for cell_type and the second value is for driver_strengh.
In the Type field, you can specify any of the columns, such as power_total_mean or power_total_median. The specified type
is used with the rank column to get the abnormal cells. Here, an abnormal cell means the specified column value's sequence
violated the rank. If the count is high, such as 100+, this cell may have potential issues and is suggested as a dont_use cell.
Use Customized Columns to add your own custom columns. Click the + symbol next to Customized Columns to add the
column name and definition.
When you click Apply, the new custom column is added to the power analysis table.
Use Columns Filter (    ) to filter the columns that are displayed.
Provides a compare graph.
Enables you to check dont_use cells setting in the design.
Supports power distribution analysis.
In GroupBy, you can choose from the following options:
In By, you can choose from options such as capacitance, coupling capacitance, resistance, or all.
You can check fanout of clock cells. For example, for CKBD4 instance power by fanout, the filter can be
driver_base_pin in ("base_pin:CKBD4BWP/Z","base_pin:CKBD2BWP/Z"):
Length Summary
Displays the length summary for the selected datasets. If the number of selected datasets is high, their names are scrolled through at the
top.
Length Comparison
Click       at the top-right corner of the Length Distribution for Nets widget to view the length comparison for nets.
The Sum_length Distribution for Nets page:
Shows net change distribution and net length distribution.
Shows different type of net statistics and distribution. For example:
Filter: "sum_length>100 and wire_count>20 and driver_base_pin.str.contains('X1').values"
GroupBy: is_clock, route_rule, or num_loads
by: net or layer
Allows you to focus on only those nets that are on the critical path.
Enables you to get clock routing layer usage. Filter can be is_clock==True and route_rule=="Trunk" or is_clock==True
and route_rule=="Leaf".
Shows the DRC distribution of a net or cell.
DRC_type: net_drc or inst_drc
GroupBy (row): Specifies the net attribute to group by, such as is_clock:
By (column): subtype or layer. With layer, you get layer-wise DRC distribution per DRC type.
Shows the layer-based DRC distribution.
DRC_type: layer_drc
GroupBy (row): subtype
By (column): layer
Shows the crosstalk distribution:
Silicon Sight App
Introduction
Datasets
Specifying Parameters
Modifying Filters
Indicators
Rules
Result
Violation Summary
Detailed Filter Result
Summary Table Result
By Block
Trend Table Result By Rule
Treemap Chart Result
Filter Paths
Detailed Information for One Path
Filter Groups
Introduction
The Silicon Sight app can be used for the following:
Apply a rubric to the implementation results to determine the handoff quality and identify design issues.
Recalculate new useful fields, including physical info on all violated paths.
Categorize the root issues like constraints, routing, clock, and so on.
Suggest solutions to solve the issue quickly.
Rapidly scan results for potential design challenges and failures, such as the following:
Path depth too large
Critical timing path placed in a congested area
Limiting constraints present on failing paths
Track results across the flow or between different runs.
Verify that old issues are resolved and new issues are not introduced.
Datasets
Multiple datasets are supported with the same design name. Each dataset is considered as one block in the app.
Besides the selected datasets, each Silicon Sight project will also include the datasets with the selected tags.
The Silicon Sight app supports Innovus and Tempus databases. Genus is not supported.
You can also modify the tags for a project. This makes it easy to control the incoming data without redefining the project.
Specifying Parameters
1. Choose a view (Setup view or Hold view).
2. Choose options:
slack threshold: Only the paths with value less than the specified threshold are analyzed.
severity: For each rule, the top 1/4 quantile violated paths are considered severe and kept. Switching on the Severity option
will show only the violations with "high severity". The tool will check each indicator distribution on all violated paths and
choose the outlier located out of (Q1 - 0.5* (Q3-Q1) ~ Q3 + 0.5 * (Q3-Q1) )
major: For each path, determines the major violated rules. If the major toggle is turned on, the engine will calculate each
rule's percentage delay in the slack.
By default, the major toggle is turned off and all reasons are regraded as minor reasons.
weight type:
If Heuristic is selected, a fixed-weight threshold is used. Rules with values over the threshold will be marked major.
If Statistics is selected, a statistical method is used to judge if a rule is major. Typically, if the rule is rare, it will be major.
weight threshold: Specifies the threshold weight.
3. Click APPLY to get the Filter result with rules.
Modifying Filters
Some threshold settings that are used in the filter condition are:
Threshold                         Value     Description
Slack threshold                   0         Only paths with slack < 0 are analyzed.
P2p detour threshold              1.2       p2p net length / p2p manhattan length. Used in the total_p2p_detour indicator.
Slew threshold                    0.2       DRV rule. Used in the slew_violated_total indicator.
Load threshold                    0.2       DRV rule. Used in the load_violated_total indicator
Global cell density               0.7       Max global cell density setting. Used in the max_local_density indicator
threshold
Hinst size (children inst         5000      Only hinst > 5000 local insts are considered for counting purposes. Used in the hinst_count
count)                                      indicator.
You can change the threshold settings and other filter conditions by clicking the + next to Change filter conditions here.
This opens the Config form where you can change threshold and cost settings, filter rules, and so on.
For information on setting cost and related indicators, see Indicators.
For information on defining filter rules, see Rules.
The Config form also has an Indicator Distribution section, where you can check the distribution of specified indicators for a block:
In the Path Group Suggestion section of the form, you can specify a path group name and its setting.
The setting can be in terms of weight, effort_level, or slack_adjustment, as shown below.
If the auto toggle is enabled, path group and setting will be set automatically in the scripts and you do not need to specify them manually.
Indicators
A total of 50 indicators are calculated for each single path and can be used in the rules. As shown below, the number of indicators
calculated is dependent on the cost setting (low/medium/high) you select. In a low cost setting, only a part of the indicators are
calculated, which can save time but miss some indicators.
For Tempus timing_only db, the maximum cost is medium. The high setting is not supported.
If there are no physical paths, only medium cost is supported.
Category       Indicator                                         Description                 Reference            Type       setup/hold
Value for Rules
Constraints    dont_touch_celldelay_ratio                        Total dont touch inst       >= 0.2               float      both
delay / path_delay
dont_touch_netdelay_ratio                         Total dont touch net        >= 0.2               float      both
delay / path_delay
external_delay_ratio                              External_delay /            >= 0.2               float      setup
path_delay
path_delay_over_period_ratio                      Path_delay / period         >= 0.2               float      setup
zero_wire_model_slack                             Replace path net delay      <=                   float      setup
to 0, keep inst delay       {slack_threshold}
and recalculate slack
is_propagated                               If path contains ideal      = False      boolean   both
clock (clock delay is 0),
return False
negative_setup_wns_total                    Loop all inst on each       >=1          int       hold
violated hold path,
check the inst worst
setup slack, return inst
count if inst's slack<0.
Inst's slack is the worst
path crossing this inst.
negative_hold_wns_total                     Loop all inst on each       >=1          int       setup
violated setup path,
check the inst worst
hold slack, return inst
count if inst's slack<0.
Inst's slack is the worst
path crossing this inst.
inst_is_fixed_total                         Total "is_fixed = True"     >=1          int       both
insts count in the path
inst_is_clock_total                         Total "is_clock= True"      >=1          int       both
insts count l
e.g.CKBD/CKND
Crosstalk   si_delay_ratio                              Total si_delay / path       >= 0.2       float     both
delay
Library     worst_inst_delay_ratio                      worst_inst_delay / path     >= 0.2       float     setup
delay
Routing     worst_net_delay_ratio                       worst_net_delay / path      > 0.2        float     setup
delay
total_p2p_detour                            Loop each p2p               >= 1         int       setup
(pin2pin) if p2p net
length / p2p manhattan
length > {p2p detour
threshold}, return the
p2p count on the path
Placement   cumulative_manhattan_length                 Cumulative p2p              >= 100 um    int       setup
manhattan length
max_local_density                           Loop each the inst on       >= {global   float     both
the path, return the max    density}
density value. the
value is calcluated by
inst area in specified
grid devide unit grid
area. Unit Grid is 5 inst
height.
over_global_density_total                    Loop all the inst on the    >=1      int       both
path, return over {global
cell density} inst count.
Global cell density is
inst area in specified
grid devide grid area.
Grid is 5 inst height.
over_blkgs_density                           Loop all the inst on the    = True   boolean   both
path, check if the inst
local density over
corresponding
blockages density
settings.
Path        logic_level                                  Logic level count on the    >= 5     int       setup
Structure                                                path
buffer_inverter_count                        Buffer count +              >= 15    int       setup
inverter_count
none_buffer_logic_level                      Logic level - buffer        >= 15    int       setup
count - inverter count
max_fanout                                   Loop all the inst fanout    >= 10    int       setup
on the path, return
max_fanout
total_is_hvtcell                             Hvt inst count on the       >= 3     int       setup
path
total_is_lvtcell                             Lvt inst count on the       >= 3     int       both
path
power_domain_count                           power_domain_count          >= 2     int       both
zigzag_placement_ratio                       Cumulative p2p              >= 1.2   float     both
manhattan length /
startpoint - endpoint
distance
total_is_macro                               Paths contain macro         =True    boolean   both
total_is_latch                               Paths contain latch         =True    boolean   both
total_is_integrated_clock_gating             Paths contain               =True    boolean   both
integrated_clock_gating
total_is_level_shifter                       Paths contain               =True    boolean   both
level_shifter
cppr_adjustment                              cppr_adjustment             >= 0.1   float     both
hinst_count                                  Return big hinst_count,     >= 2     int       both
the hinst must contain
at least
{hinst_size(default
5000)} insts.
is_off_cycle                               Off cycled paths:            =True    boolean   both
launching/capturing
clock edge is different
or launching/capturing
clock period is different
data_net_is_clock_total                    Data path contains           >= 1     int       both
clock net count
zigzag_rams                                Path crossing rams with      =True    boolean   both
zigzag inst placement
total_zigzag_farthest_is_buffer            Check the farthest           True     boolean   both
instance type, must be
buffer/inverter and
fanout is 1. Returns
True if the zigzag was
due to buffer insertion.
Zigzag path means the
paths is detoured or
jogged like "Z".
DRV        slew_violated_total                        slew_violated over           >= 3     int       both
{slew_threshold} count
load_violated_total                        load_violated over           >= 3     int       both
{load_threshold} count
Others     skew                                       Path skew                    >= 0.1   float     both
over_holdtns_threshold_total               Loop all inst on the         >=1      int       both
violated path, check the
grid hold TNS (all the
flop's slack in the grid),
and return the inst count
if the hold tns <=-0.5.
below_grid_density_count_threshold_total   Loop all the long net        >=1      int       both
wire on the path, the net
crossing multiple grid,
for each grid if the grid
density over
{density_threshold},
exclude the grid. if the
grid count < 3, the net is
congested and if these
kind of net count >1 in
the path, it means the
path crossing
congested area.
Features   in_channels                                Indicator                    True     boolean   both
near_rams=True and
loop all the inst on the
path calculate
in_halo_inst count /total
inst count > 0.9
near_rams                                            If more than 3 insts in        True                boolean      both
ram halo. Ram halo's
width = row_height * 5
cross_channels                                       Indicator in_channels =        True                boolean      both
True and zigzag.
Zigzag path means the
paths is detoured or
jogged like "Z".
Rules
1. Define a custom rule in yaml with the following attributes:
name: The rule's name
condition: Use indicators to write the filter expression.
category: Can be a list to show the violation in summary.
suggestion: Specifies suggestions for fixing this violation.
- category:
- Placement
- Macro
condition: below_grid_density_count_threshold_total==1&near_rams==1&slack<=0
name: Critical path with high density near sram
suggestion:
- Add a density blockage
- Move SRAMs
- Control by guide
2. Specify the filter conditions for violations and save the rule template.
JedAI uses the default filter rules to calculate violations. If you are a first time user entering the project, click Change filter
conditions here + to check and change filter rules.
3. Edit the rules.
Silicon Sight allows you to define rules based on the predefined indicators to find violated datasets/paths.
Use the default rules at the beginning. Click the Edit icon (     ) to edit the rules.
Choose the indicators in the left pane and add/edit rules in the right. For each rule, category, condition, and name are
mandatory while weight and suggestion are optional.
You can define your own rule, save it as a template, and then apply to other projects.
Result
Violation Summary
The Violation Count chart shows the violation comparison from various categories for different flow phases. The affected phases are
displayed from top to bottom as per the flow order.
To customize the Violation Count chart:
1. For each flow phase, you need to select one specific version. By default, the latest version is used. Click the + symbol next
to Violation Count in the Silicon Sight app to change the version for each dataset.
2. The Violation Count chart can be displayed in three different formats: bar (   ), line (     ), and area (   ). Click the picture icon to
change to the required format type.
3. The Violation Count chart is clickable. You can click any stage (flow phase) name in the chart to get a detailed violation
comparison between different versions for the selected stage. Similarly, click the         icon to get a comparison between different
stages with the selected versions.
Detailed Filter Result
The detailed Filter Result displays results in two different formats: Summary table and Trend table.
Summary Table Result
You can display the table by rule or block. Click the          or         toggle button on top of the table to switch between the two
views.
By default, all rows with count equal to 0 are hidden. Click the           button to show all rows.
By Block
The Block level table compares violated categories/rules/hinst_groups for each block.
Click the + or - symbol to expand or collapse the rows.
If the major toggle is turned on, the tool will highlight all the major reasons in the table and chart while graying out minor reasons.
Click an event in a row to view details as follows:
Click the block to view the path summary for all category.​
Click the category to view the path summary for one category.​
Click the rule to view the path summary for one category + one rule.​
Click the hinst group to view the path summary for one category + one rule + one hinst.
Save violations to the dashboard:
Click Save to save the data to the Dashboard app. User can then view it without rerunning silicon_sight in Dashboard.
Trend Table Result By Rule
The Rule level will show the violation trend for selected datasets from the stage/version view.
On the left is the trend table, and on the right is the treemap chart.
If the increased percentage and increased count is higher than benchmark, the dataset appears highlighted as shown below. The
highlight condition is set in the Filter Rule page.
Click an event node on the Violation Trend chart to view details:
Clicking a node for one rule displays the path summary for one category and one rule.
Clicking the node for sum displays the path summary for all categories
Treemap Chart Result
Click the second/third level partitions in the treemap graph to expand.
Filter Paths
The Filter Paths section shows the violated rules and suggestions for each path. Click the colored circle for a violated rule to view the
corresponding indicators in the table, as shown below.
You can filter the table by clicking the    icon. You can filter rows by percentage or value.
You can also filter results by typing text in the Type anything and press enter to filter results in the table global filter text box as
shown below:
The start and end points appear abbreviated by default. Place the cursor over a point to view its complete name.
You can use regular expression (regex) patterns to filter the text column values in tables. For example, you can use regex patterns
to filter start points, as shown below:
Click a row to generate the detailed information for each path.
Detailed Information for One Path
Path widget is on the left. Options are similar to those in Innovus.
By default, the logic path is shown but it can be switched to the physical path.
Press z to zoom in.
Press Shift+Z to zoom out.
Use the right mouse button to zoom into a specific area.
Press f to fit the display.
Click one item (inst/net/ram) and press q to query for detailed information.
Path summary information
Path detail information: This shows violations for each inst, as depicted below.
Chain analysis of failing timing paths is supported. For each failing path, you can see N previous and next stages with respect to
that failing path. Here, N is the specified chain level.
To enable chain analysis and dump the specified level of previous and next paths, add the following settings to the
export_cfg.yaml file. For more information, see Extracting Data from Genus, Innovus, and Tempus.
chain_path: true
chain_levels: 3 #3 is default
This creates a chain analysis summary of 3 previous and next paths with respect to a failing path.
Filter Groups
You can use filter groups to create filter rules.
For example, you can create a filter group to hide some paths with known issues, as shown below:
You can modify the existing rules of a filter group:​
1. Click the name of an existing filter group.​
2. Modify the rules in the left section.
3. Add comments to clarify the purpose of filter group rules (optional).​
4. Click SAVE.
Timing Matrix App
Datasets
One Timing Matrix project can support only one dataset.
It is recommended that this application should be run on a dataset with a hierarchical structure.
The Timing Matrix app supports Innovus, Tempus, and Genus databases. The app can be run only with a hierarchical design; a
flat design is not supported.
Specifying Parameters
Choose a view (Setup view or Hold view), specify a value for Slack threshold (Default=0), and then click APPLY.
Result
Hinst Summary
Shows the Departing, Arriving, and Inside indicators (WNS/TNS/FEP) for each hinst.
Turn on the Fill NA toggle to remove the rows that have all NA values. By default, this toggle is turned off.
Click +/- in the Hinst Name column in the Summary table to expand or collapse the table by hinsts.
Select the check box before an hinst name (for example, i_dsp in the screenshot above) under Hinst Name to add that hinst to the
Hinst Matrix calculation.
Click the cross symbol next to an hinst name in the Selected Hinsts list to remove that hinst from the Hinst Matrix calculation.
Hinst Matrix/Cell Type Matrix
Shows the WNS/TNS/FEP values from one hinst to another hinst.
The indexes, headers, cells in orange can be clicked to generate more detailed information about the corresponding path.
Paths Information Between Two Hinsts/Cell Types
Shows information from one hinst/cell type to another hinst/cell type.
In the image below, the first table shows the summary WNS/TNS/FEP values for each pair of hisnt/cell types.
Click a row to filter Path Information in the second table below.
The second table below shows all paths between two hinsts/cell types.
Click a row to generate the detailed information for that path.
Path Information for One Path
The graph shows the summary values for current, previous, and posterior paths.
The table shows pin-level information for this path.

---
## JedAI Storage

The Cadence JedAI Platform provides a back-end data management service for different types of
data, including waveform and blob data. The architecture diagram below shows how JedAI
interacts with different kinds of components to manage data storage and retrieval.
The CDP utility (cdp_utility) is part of the Cadence JedAI Platform and is a command-line interface
for data management on JedAI. Applications and end users can use the CDP utility command line
to store, load, query, and delete blob data from JedAI. Waveform data has characteristics such as
high velocity and volume, which require faster reading and writing. JedAI provides the back-end
support to accommodate these requirements.
The following storage-related components are included in the JedAI release:
libjedai.so – The JedAI library
cdp_utility – A command-line utility for JedAI
The JedAI catalog manages the metadata for the stored data, including blob data and Verisium
Waveform Database (VWDB) data. The following key concepts are supported in the catalog:
Entity           An entry to record the metadata information for different type of data, including
but not limited to tool, vwdb, snapshot, log, report, tag, and so on.
Version          Is maintained to track the history of the data.
Guid             A global unique identifier used to identify data uniquely. A includes two parts
separated by the * character:
The first part is a uuid which is shared among different versions of an entity
The second part is the auto incremented version id.
For example: 161cac85-0bea-4098-a5a9-17223b862a99*1
Association      A link from one entity to another. For example, you want to assign a new tag,
"new_run", to a snapshot — you can then have a "new_run" entity a and a
snapshot entity b, and associate a to b.
Loading is a term for retrieving data from JedAI:
While storing blob data, all relative paths are converted to full paths and stored in JedAI.
While loading, relative paths are converted to full paths based on the current working directory
and the matching directories from JedAI are loaded.
Related Information
Using the CDP Utility To Manage Data
How Applications Use JedAI Data
Using the CDP Utility To Manage Data
JedAI uses a command-line utility called cdp_utility to manage data.
The general format of the CDP utility is as follows:
cdp_utility command <argument1> [<argument2>] [options]
The following operations are supported:
Registering Data with cdp_utility
Updating Data with cdp_utility
Storing Data with cdp_utility
Loading Data with cdp_utility
Querying Data with cdp_utility
Querying Metadata with cdp_utility
Deleting Data with cdp_utility
Deleting Metadata with cdp_utility
Associating Entities with cdp_utility
Mount Operations with cdp_utility
Limitations of cdp_utility
The current cdp_utility has some limitations:
cdp_utility does not maintain the timestamp and access permissions of the original blob
data.
cdp_utility maintains the soft links of only those files/folders that are stored in JedAI. If a soft
link is pointing to a file or folder that is not stored in JedAI, the soft link is broken.
Related Information
Appendix F: The cdp_utility Commands
Registering Data with cdp_utility
Registering means saving the metadata into the catalog. You can use
the cdp_utility register command to register metadata in the catalog.
Usage:
cdp_utility register <data_type> <-k key=value> [-k key=value, ...]
To register an entity, you must specify its data_type as well as at least one key-value pair. The
register command returns the guid for the data registered.
For example:
cdp_utility register snapshot -k name=old_snap
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*1. The guid can then
be used to store the data.
Related Information
Storing Data with cdp_utility
Updating Data with cdp_utility
Appendix F: The cdp_utility Commands
Updating Data with cdp_utility
Use the cdp_utility update command to update the metadata in the catalog. You can simply
update the meta data key-value pairs or create a new version of meta data.
Usage:
cdp_utility update <guid> <-k key=value> [-k key=value, …] -v
Updating an entity
To update an entity, the guid must be specified along with at least one key-value pair. The
command returns the guid for the data updated.
For example:
cdp_utility update 161cac85-0bea-4098-a5a9-17223b862a99*1 -k
path=/vols/datastore/design1/snapshot_old
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*1. The metadata for the
guid is updated.
Creating a new version of an entity
To create a new version of entity, -v should be specified. It automatically creates a new version of
an entity with the specified key-value pairs.
For example:
cdp_utility update 161cac85-0bea-4098-a5a9-17223b862a99*1 -k
path=/vols/datastore/design1/snapshot_old -k name=snapshot_old_v2 -v
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*2, where *2 indicates
the new version of the entity.
Related Information
Registering Data with cdp_utility
Storing Data with cdp_utility
Appendix F: The cdp_utility Commands
Storing Data with cdp_utility
Use the cdp_utility store command to store blob data in JedAI.
Usage:
cdp_utility store <path> [<path>,..] [-s | -f] [-k guid=<guid>]
To store files under a specific directory and its subdirectories as blob data in JedAI, use the
following command:
cdp_utility store <full_path | relative_path> [-k guid=<guid>]
If -k guid=<guid> is specified, this command returns the guid as the key to locate the data stored in
JedAI. The guid can be used for querying, loading, and deleting the data. However, if -k guid=
<guid> is not specified, this command returns the full path as the key to where the data is originally
located. The full path then can be used for querying, loading, and deleting the data stored in JedAI.
For example:
cdp_utility store snapshot_old
This command will return a full path name. For example: /vols/datastore/design1/snapshot_old.
cdp_utility store snapshot_old -k guid=161cac85-0bea-4098-a5a9-17223b862a99*1
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*1.
Note: JedAI stores the leaf directory and its contents including subdirectories. For example, if path
“/a/b/c” is provided, only the files/subfolders of c and folder c will be stored with the full path key
/a/b/c.
Storing multiple paths with a single command
The store command allows you to include multiple paths in the list, delimited with space. Each path
will be stored separately. The list of full paths will be returned as the result.
For example:
cdp_utility store snapshot_old snapshot_new
This command will store both snapshot_old and snapshot_new, and
return /vols/datastore/design1/snapshot_old and /vols/datastore/design1/snapshot_new as
the result.
Storing a single file only
The store command also allows you to store a single file in JedAI. For example:
cdp_utility store snapshot_old/test.txt
This command will return the full path /vols/datastore/design1/snapshot_old/test.txt,
indicating that only one file is stored.
Overwriting data
If the full path has already been stored, an error will be reported saying "path is duplicated". In
case you need to overwrite the data already stored in JedAI, you can run the following command:
cdp_utility store <full_path | relative_path > -f
-f forces the overwrite. Keep in mind that the overwrite is to add new files/folders and overwrite the
old files/folders that have the same name. However, the operation will keep the old files/folders if
there are no new files/folders with the same name. For clean reload, you need to first delete the
existing data from JedAI and then re-store the data.
Storing only the link to a directory
If you want to store only the link to a directory in JedAI without storing any real data, you can run the
following command:
cdp_utility store <full_path | relative_path> -s
Here, -s indicates that only the link will be stored.
If only the link is stored in JedAI, JedAI cannot guarantee data availability if the original path
is deleted or moved.
Cadence does not recommend using the store command to save the soft link information.
Instead, use the register command to save the soft link as metadata.
For example:
cdp_utility store snapshot_link -s
It returns /vols/datastore/design1/snapshot_link.
Related Information
Registering Data with cdp_utility
Updating Data with cdp_utility
Appendix F: The cdp_utility Commands
Loading Data with cdp_utility
Use the cdp_utility load command to load or retrieve data from JedAI.
Usage:
cdp_utility load <source_path | guid> <target_path> [-n]
This command will create the <target_path> folder and load all contents from the specified source
path or guid into the target folder.
Loading data using the full path or relative path
You can use the original source path, full path, or relative path to load the data. JedAI provides the
relative path as an option in the command, assuming that the current running directory is the same
as the directory in which the data was stored. For example, under the folder
/vols/datastore/design1, run the following command:
cdp_utility load snapshot_old auto_1234
This will try to load the contents that are stored in the
key /vols/datastore/design1/snapshot_old. JedAI loads
the /vols/datastore/design1/snapshot_old folder itself and its contents into auto_1234 under the
current folder. In case the key /vols/datastore/design1/snapshot_old cannot be found, JedAI
reports the error "Not found for the <path>".
Loading contents based on guid
cdp_utility load 87a334b3-a9c7-4962-a7e3-f75c69314fee*1 auto_2345
This command will load the contents stored in the guid 87a334b3-a9c7-4962- a7e3-
f75c69314fee*1 into auto_1234 under the current folder.
Loading only the link
When you store data using the -s option, JedAI only stores the link. To load the corresponding data,
JedAI creates a local folder with a subfolder that is soft-linked to the original path.
For example:
cdp_utility load snapshot_link auto_2345
Inside the auto_2345 folder, snapshot_link is soft-linked
to /vols/datastore/design1/snapshot_link.
Loading only the contents of a path
In case you need to load only the contents of a path, run the following command:
cdp_utility load snapshot_oldauto_1234 -n
This will load only the contents of /vols/datastore/design1/snapshot_old, but not the folder itself,
into the auto_1234 folder. -n indicates 'non-inclusive of the folder'.
Related Information
Registering Data with cdp_utility
Storing Data with cdp_utility
Updating Data with cdp_utility
Appendix F: The cdp_utility Commands
Querying Data with cdp_utility
Querying allows you to find specific content within JedAI. Use the
following cdp_utility commands to query data in JedAI:
list
find
Usage:
list
cdp_utility list <path> [-w|-b|-d |-r]
Lists the path from waveform data, as well as files/folders recursively or non-recursively from the
stored blob data.
To list all waveform runs
cdp_utility list / -w -r
/vols/datastore/design1/run1/good and /vols/datastore/design1/run2/bad will be returned.
Keep in mind that the waveform run was generated by Xcelium and stored in JedAI; the list
command returns the path where the original waveform was stored. You use the full path as the key
to identify each run.
To list all files/folders under the given full path recursively
cdp_utility list /vols/datastore/design2/snapshot_new -r
With -r, this command returns all folders/files recursively under
the /vols/datastore/design2/snapshot_new folder.
To list only the files and folders under a full path
cdp_utility list /vols/datastore/design2/snapshot_new
find
cdp_utility find string [-w|-b|-d ]
Searches for the specified string within the file or folder names from the waveform and blob data.
To find a string in all stored folders
cdp_utility find snapshot_new -d
Searches only for the snapshot_new folder.
To find a string in all stored files
cdp_utility find snapshot_new -b
Searches for snapshot_new in the file names and the path to the files.
Related Information
Updating Data with cdp_utility
Querying Metadata with cdp_utility
Appendix F: The cdp_utility Commands
Querying Metadata with cdp_utility
In addition to data, you can also use cdp_utility to query and search the metadata within JedAI.
Use the following cdp_utility commands to query the metadata in JedAI:
getmeta
find
Usage:
getmeta
cdp_utility getmeta [-k key=value, …] [-t <type>] [-a] [-g]
Retrieves a list of entities that match the specified key-values, as well as the specified data type.
findmeta
cdp_utility findmeta “<keyword> [<keyword>.. ]” [-t <type>] [-a] [-g]
Searches for the specified keyword string within the entity meta data, and also filters by the
specified data type.
To list entities that match the key value pair:
cdp_utility getmeta -k name=snapshot_new
To list entities that match the key value pair and data type:
cdp_utility getmeta -k name=snapshot_new -t snapshot
To list entities and their history versions that match the key value pair:
cdp_utility getmeta -k name=snapshot_new -a
To list guids of entities that match the key value pair:
cdp_utility getmeta -k name=snapshot_new -g
To find entities that match the keyword:
cdp_utility findmeta "snapshot"
To find entities that match the keyword and specified data type:
cdp_utility findmeta "snapshot" -t snaphot
To find entities that match the keyword, and return the entities and history version:
cdp_utility findmeta "snapshot" -a
To find entities that match the keyword, and return only the list of guids of the entities and
history version:
cdp_utility findmeta "snapshot" -g
Related Information
Updating Data with cdp_utility
Querying Data with cdp_utility
Appendix F: The cdp_utility Commands
Deleting Data with cdp_utility
Use the cdp_utility delete command to delete content from JedAI.
Usage:
cdp_utility delete <path|guid> [-f]
Deletes the stored blob data in JedAI based on the specified path or guid. <path> can be either
relative or a full path.
Once the data has been deleted, the corresponding metadata is removed as well.
A prompt is displayed to confirm the deletion; however, you should proceed with caution.
Make sure that the blob data in JedAI is no longer needed before running this command.
If -f is specified, cdp_utility will not display a prompt asking for confirmation and the data
in JedAI will be deleted.
Related Information
Deleting Metadata with cdp_utility
Appendix F: The cdp_utility Commands
Deleting Metadata with cdp_utility
Use the cdp_utility deletemeta command to delete metadata from JedAI.
Usage:
cdp_utility deletemeta <guid> [-a]
If -a is specified, cdp_utility will delete all versions of the specified metadata.
Related Information
Deleting Data with cdp_utility
Appendix F: The cdp_utility Commands
Associating Entities with cdp_utility
Use the cdp_utility associate command to associate entities for JedAI metadata.
Usage:
cdp_utility associate <source_guid> <target_guid>
Example:
Assume one snapshot entity has the guid 161cac85-0bea-4098-a5a9- 17223b862a99*1 and a "test"
tag has the guid eb92e3d4-2a90-4a4b-8a8a- 1c2c3f092845*1. The following command associates
the tag to the snapshot:
cdp_utility associate 161cac85-0bea-4098-a5a9- 17223b862a99*1 eb92e3d4-2a90-4a4b-8a8a-
1c2c3f092845*1
Related Information
Appendix F: The cdp_utility Commands
Mount Operations with cdp_utility
A file interface for JedAI is provided through a mount point that supports standard filesystem
operations, such as reading and writing after an open() system call and ls, mkdir, and cp shell
operations. The mount point is only accessible by the current user, but the data stored in the mount
point follows filesystem permissions and is visible to any user across machines that also mount the
file interface.
Usage:
cdp_utility mount [<path>] [-u]
You must set the $CDNS_JEDAI_SERVER=file://<path> environment variable before using the
command. By default, JedAI uses the path set in this environment variable for mounting.
This command requires additional dependencies installed in the system to support FUSE:
fuse, fuse3, fuse-libs, and fuse3-libs.
To mount a file interface on an existing directory:
cdp_utility mount <path>
To list the current mountpoints or mounted paths for the current user:
cdp_utility mount
To unmount a file interface:
cdp_utility mount <path> -u
Related Information
Appendix F: The cdp_utility Commands
How Applications Use JedAI Data
Xcelium
WaveMiner
Semantic Diff
Xcelium
Xcelium has the capability to capture waveform data and store it in JedAI through the VWDB
interface. Run Xcelium with the following environment variables for each set of dumping
commands.
setenv CDNS_ENABLE_SHM2VWDB 1
setenv CDNS_XWD_CDB 1
setenv CDNS_XWD_MOZART SERVER $CDNS_JEDAI_SERVER
setenv CDNS_XWD_CDB_PATH
${CDNS_INST_DIR}/tools/lib/64bit/libvwdbc.so
setenv CDNS_XWD_MOZART_PATH $CDNS_JEDAI_PATH/libjedai.so setenv
CDNS_XWD_MOZART_AUTO_NAME 1
VWDB will directly stream into JedAI, and you can use the full hierarchical name to access it from
JedAI like you use vwdb files. Refer to the Creating a VWDB Probe Database section in Debugging
with Indago (on support.cadence.com) for more details on the Xcelium command usage.
WaveMiner
Setting the Environment
setenv CDNS_XWD_CDB 1
setenv CDNS_XWD_CDB_WAVEDIFF 1
setenv INDAGO_ROOT /grid/avs/install/indago/AGILE/latest setenv
INDAGO_DISABLE_DELETE_DESIGN_DB_INDICES 1
setenv INDAGO_LIBDAC_LOCATION
<$InstallDir/tools/lib/64bit/libdac.so> setenv CDNS_XWD_CDB_PATH
<$InstallDir/tools/lib/64bit/libvwdbc.so> setenv CDNS_JEDAI_PATH
<$InstallDir/tools.lnx86/jedAI/lib/64bit/>
setenv CDNS_JEDAI_SERVER <file://$HOME/vwdb_jedai> setenv CDS_LIC_FILE <port@server>
setenv LD_LIBRARY_PATH <LD_LIBRARY_PATH>
$installDir indicates where the tools are installed. CDS_LIC_FILE indicates where the license
server is, and LD_LIBRARY_PATH needs to include the path to the correct gnu C++ library (for
example, /grid/common/pkgs/gcc/v9.3.0p4/lib64) as well as include the path to
libcdsCommon_sh.so.
Running Xcelium
xrun +vwdb+shm2vwdb=1 -64 -sv testbench.v src/fifo.sv - lwdgen -input ida_probe.tcl -
access +rwc -clean - xmlibdirpath snapshots/old_snap –snapshot wm1
Storing the snapshots in JedAI
cdp_utility store snapshots/old_snap
cdp_utility store snapshots/new_snap
JedAI will return the full paths. For example:
/vols/datastore/snapshots/old_snap, /vols/datastore/ snapshots/new_snap
Running WaveMiner
WaveMiner needs to load the waveform data and blob data stored in JedAI before it starts running.
Namely, WaveMiner needs to load two Xcelium snapshots and two lists of waveform data for
comparison. The following command illustrates what types of data need to be gathered before
running:
verisium -waveminer-xmlibdirpath_golden
/vols/datastore/snapshots/old_snap -xmlibdirpath_new
/vols/datastore/snapshots/new_snap-wave_new
/vols/datastore/design1/run/bad-wave_golden
/vols/datastore/design2/run/good
/vols/datastore/snapshots/old_snap and /vols/datastore/snapshots/new_snap are full paths to
the snapshots parent directory, which are stored in JedAI as blob data, while
/vols/datastore/design1/run/bad and /vols/datastore/design2/run/good are stored in JedAI as
waveform data.
Semantic Diff
Setting the Environment
setenv CDNS_XWD_CDB 1
setenv INDAGO_ROOT /grid/avs/install/indago/AGILE/latest
setenv INDAGO_DISABLE_DELETE_DESIGN_DB_INDICES 1
setenv INDAGO_LIBDAC_LOCATION <$InstallDir/tools/lib/64bit/libdac.so>
setenv CDNS_XWD_CDB_PATH <$InstallDir/tools/lib/64bit/libvwdbc.so>
setenv CDNS_JEDAI_PATH <$InstallDir/tools.lnx86/jedAI/lib/64bit/>
setenv CDNS_JEDAI_SERVER <file://$HOME/vwdb_jedai>
setenv CDS_LIC_FILE <port@server>
setenv LD_LIBRARY_PATH <LD_LIBRARY_PATH>
$installDir indicates where the tools are installed. CDS_LIC_FILE indicates where the license
server is, and LD_LIBRARY_PATH needs to include the path to the correct gnu C++ library (for
example, /grid/common/pkgs/gcc/v9.3.0p4/lib64) as well as include the path to
libcdsCommon_sh.so.
Running Xcelium
xrun -64 -sv testbench.v src/fifo.sv -clean -xmlibdirpath snapshots/old_snap -snapshot
sd1
xrun -64 -sv testbench.v src/fifo.sv -clean -xmlibdirpath snapshots/new_snap -snapshot
sd1
This will generate two snapshots under different folders, old_snap and new_snap.
Storing the snapshots in JedAI
cdp_utility store snapshots/old_snap
cdp_utility store snapshots/new_snap
JedAI will return the full paths. For example:
/vols/datastore/snapshots/old_snap, /vols/datastore/ snapshots/new_snap
Running semantic_diff
Use the two paths collected in the last step and run semantic_diff on the two snapshots:
verisium -semanticdiff –xmlibdirpath_golden
/vols/datastore/snapshots/old_snap –xmlibdirpath_new
/vols/datastore/snapshots/new_snap –snapshot sd1

---
## Data Catalog

Using the CDP Utility To Manage Data
How Applications Use JedAI Data
Using the CDP Utility To Manage Data
JedAI uses a command-line utility called cdp_utility to manage data.
The general format of the CDP utility is as follows:
cdp_utility command <argument1> [<argument2>] [options]
The following operations are supported:
Registering Data with cdp_utility
Updating Data with cdp_utility
Storing Data with cdp_utility
Loading Data with cdp_utility
Querying Data with cdp_utility
Querying Metadata with cdp_utility
Deleting Data with cdp_utility
Deleting Metadata with cdp_utility
Associating Entities with cdp_utility
Mount Operations with cdp_utility
Limitations of cdp_utility
The current cdp_utility has some limitations:
cdp_utility does not maintain the timestamp and access permissions of the original blob
data.
cdp_utility maintains the soft links of only those files/folders that are stored in JedAI. If a soft
link is pointing to a file or folder that is not stored in JedAI, the soft link is broken.
Related Information
Appendix F: The cdp_utility Commands
Registering Data with cdp_utility
Registering means saving the metadata into the catalog. You can use
the cdp_utility register command to register metadata in the catalog.
Usage:
cdp_utility register <data_type> <-k key=value> [-k key=value, ...]
To register an entity, you must specify its data_type as well as at least one key-value pair. The
register command returns the guid for the data registered.
For example:
cdp_utility register snapshot -k name=old_snap
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*1. The guid can then
be used to store the data.
Related Information
Storing Data with cdp_utility
Updating Data with cdp_utility
Appendix F: The cdp_utility Commands
Updating Data with cdp_utility
Use the cdp_utility update command to update the metadata in the catalog. You can simply
update the meta data key-value pairs or create a new version of meta data.
Usage:
cdp_utility update <guid> <-k key=value> [-k key=value, …] -v
Updating an entity
To update an entity, the guid must be specified along with at least one key-value pair. The
command returns the guid for the data updated.
For example:
cdp_utility update 161cac85-0bea-4098-a5a9-17223b862a99*1 -k
path=/vols/datastore/design1/snapshot_old
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*1. The metadata for the
guid is updated.
Creating a new version of an entity
To create a new version of entity, -v should be specified. It automatically creates a new version of
an entity with the specified key-value pairs.
For example:
cdp_utility update 161cac85-0bea-4098-a5a9-17223b862a99*1 -k
path=/vols/datastore/design1/snapshot_old -k name=snapshot_old_v2 -v
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*2, where *2 indicates
the new version of the entity.
Related Information
Registering Data with cdp_utility
Storing Data with cdp_utility
Appendix F: The cdp_utility Commands
Storing Data with cdp_utility
Use the cdp_utility store command to store blob data in JedAI.
Usage:
cdp_utility store <path> [<path>,..] [-s | -f] [-k guid=<guid>]
To store files under a specific directory and its subdirectories as blob data in JedAI, use the
following command:
cdp_utility store <full_path | relative_path> [-k guid=<guid>]
If -k guid=<guid> is specified, this command returns the guid as the key to locate the data stored in
JedAI. The guid can be used for querying, loading, and deleting the data. However, if -k guid=
<guid> is not specified, this command returns the full path as the key to where the data is originally
located. The full path then can be used for querying, loading, and deleting the data stored in JedAI.
For example:
cdp_utility store snapshot_old
This command will return a full path name. For example: /vols/datastore/design1/snapshot_old.
cdp_utility store snapshot_old -k guid=161cac85-0bea-4098-a5a9-17223b862a99*1
This command will return the guid 161cac85-0bea-4098-a5a9-17223b862a99*1.
Note: JedAI stores the leaf directory and its contents including subdirectories. For example, if path
“/a/b/c” is provided, only the files/subfolders of c and folder c will be stored with the full path key
/a/b/c.
Storing multiple paths with a single command
The store command allows you to include multiple paths in the list, delimited with space. Each path
will be stored separately. The list of full paths will be returned as the result.
For example:
cdp_utility store snapshot_old snapshot_new
This command will store both snapshot_old and snapshot_new, and
return /vols/datastore/design1/snapshot_old and /vols/datastore/design1/snapshot_new as
the result.
Storing a single file only
The store command also allows you to store a single file in JedAI. For example:
cdp_utility store snapshot_old/test.txt
This command will return the full path /vols/datastore/design1/snapshot_old/test.txt,
indicating that only one file is stored.
Overwriting data
If the full path has already been stored, an error will be reported saying "path is duplicated". In
case you need to overwrite the data already stored in JedAI, you can run the following command:
cdp_utility store <full_path | relative_path > -f
-f forces the overwrite. Keep in mind that the overwrite is to add new files/folders and overwrite the
old files/folders that have the same name. However, the operation will keep the old files/folders if
there are no new files/folders with the same name. For clean reload, you need to first delete the
existing data from JedAI and then re-store the data.
Storing only the link to a directory
If you want to store only the link to a directory in JedAI without storing any real data, you can run the
following command:
cdp_utility store <full_path | relative_path> -s
Here, -s indicates that only the link will be stored.
If only the link is stored in JedAI, JedAI cannot guarantee data availability if the original path
is deleted or moved.
Cadence does not recommend using the store command to save the soft link information.
Instead, use the register command to save the soft link as metadata.
For example:
cdp_utility store snapshot_link -s
It returns /vols/datastore/design1/snapshot_link.
Related Information
Registering Data with cdp_utility
Updating Data with cdp_utility
Appendix F: The cdp_utility Commands
Loading Data with cdp_utility
Use the cdp_utility load command to load or retrieve data from JedAI.
Usage:
cdp_utility load <source_path | guid> <target_path> [-n]
This command will create the <target_path> folder and load all contents from the specified source
path or guid into the target folder.
Loading data using the full path or relative path
You can use the original source path, full path, or relative path to load the data. JedAI provides the
relative path as an option in the command, assuming that the current running directory is the same
as the directory in which the data was stored. For example, under the folder
/vols/datastore/design1, run the following command:
cdp_utility load snapshot_old auto_1234
This will try to load the contents that are stored in the
key /vols/datastore/design1/snapshot_old. JedAI loads
the /vols/datastore/design1/snapshot_old folder itself and its contents into auto_1234 under the
current folder. In case the key /vols/datastore/design1/snapshot_old cannot be found, JedAI
reports the error "Not found for the <path>".
Loading contents based on guid
cdp_utility load 87a334b3-a9c7-4962-a7e3-f75c69314fee*1 auto_2345
This command will load the contents stored in the guid 87a334b3-a9c7-4962- a7e3-
f75c69314fee*1 into auto_1234 under the current folder.
Loading only the link
When you store data using the -s option, JedAI only stores the link. To load the corresponding data,
JedAI creates a local folder with a subfolder that is soft-linked to the original path.
For example:
cdp_utility load snapshot_link auto_2345
Inside the auto_2345 folder, snapshot_link is soft-linked
to /vols/datastore/design1/snapshot_link.
Loading only the contents of a path
In case you need to load only the contents of a path, run the following command:
cdp_utility load snapshot_oldauto_1234 -n
This will load only the contents of /vols/datastore/design1/snapshot_old, but not the folder itself,
into the auto_1234 folder. -n indicates 'non-inclusive of the folder'.
Related Information
Registering Data with cdp_utility
Storing Data with cdp_utility
Updating Data with cdp_utility
Appendix F: The cdp_utility Commands
Querying Data with cdp_utility
Querying allows you to find specific content within JedAI. Use the
following cdp_utility commands to query data in JedAI:
list
find
Usage:
list
cdp_utility list <path> [-w|-b|-d |-r]
Lists the path from waveform data, as well as files/folders recursively or non-recursively from the
stored blob data.
To list all waveform runs
cdp_utility list / -w -r
/vols/datastore/design1/run1/good and /vols/datastore/design1/run2/bad will be returned.
Keep in mind that the waveform run was generated by Xcelium and stored in JedAI; the list
command returns the path where the original waveform was stored. You use the full path as the key
to identify each run.
To list all files/folders under the given full path recursively
cdp_utility list /vols/datastore/design2/snapshot_new -r
With -r, this command returns all folders/files recursively under
the /vols/datastore/design2/snapshot_new folder.
To list only the files and folders under a full path
cdp_utility list /vols/datastore/design2/snapshot_new
find
cdp_utility find string [-w|-b|-d ]
Searches for the specified string within the file or folder names from the waveform and blob data.
To find a string in all stored folders
cdp_utility find snapshot_new -d
Searches only for the snapshot_new folder.
To find a string in all stored files
cdp_utility find snapshot_new -b
Searches for snapshot_new in the file names and the path to the files.
Related Information
Updating Data with cdp_utility
Querying Metadata with cdp_utility
Appendix F: The cdp_utility Commands
Querying Metadata with cdp_utility
In addition to data, you can also use cdp_utility to query and search the metadata within JedAI.
Use the following cdp_utility commands to query the metadata in JedAI:
getmeta
find
Usage:
getmeta
cdp_utility getmeta [-k key=value, …] [-t <type>] [-a] [-g]
Retrieves a list of entities that match the specified key-values, as well as the specified data type.
findmeta
cdp_utility findmeta “<keyword> [<keyword>.. ]” [-t <type>] [-a] [-g]
Searches for the specified keyword string within the entity meta data, and also filters by the
specified data type.
To list entities that match the key value pair:
cdp_utility getmeta -k name=snapshot_new
To list entities that match the key value pair and data type:
cdp_utility getmeta -k name=snapshot_new -t snapshot
To list entities and their history versions that match the key value pair:
cdp_utility getmeta -k name=snapshot_new -a
To list guids of entities that match the key value pair:
cdp_utility getmeta -k name=snapshot_new -g
To find entities that match the keyword:
cdp_utility findmeta "snapshot"
To find entities that match the keyword and specified data type:
cdp_utility findmeta "snapshot" -t snaphot
To find entities that match the keyword, and return the entities and history version:
cdp_utility findmeta "snapshot" -a
To find entities that match the keyword, and return only the list of guids of the entities and
history version:
cdp_utility findmeta "snapshot" -g
Related Information
Updating Data with cdp_utility
Querying Data with cdp_utility
Appendix F: The cdp_utility Commands
Deleting Data with cdp_utility
Use the cdp_utility delete command to delete content from JedAI.
Usage:
cdp_utility delete <path|guid> [-f]
Deletes the stored blob data in JedAI based on the specified path or guid. <path> can be either
relative or a full path.
Once the data has been deleted, the corresponding metadata is removed as well.
A prompt is displayed to confirm the deletion; however, you should proceed with caution.
Make sure that the blob data in JedAI is no longer needed before running this command.
If -f is specified, cdp_utility will not display a prompt asking for confirmation and the data
in JedAI will be deleted.
Related Information
Deleting Metadata with cdp_utility
Appendix F: The cdp_utility Commands
Deleting Metadata with cdp_utility
Use the cdp_utility deletemeta command to delete metadata from JedAI.
Usage:
cdp_utility deletemeta <guid> [-a]
If -a is specified, cdp_utility will delete all versions of the specified metadata.
Related Information
Deleting Data with cdp_utility
Appendix F: The cdp_utility Commands
Associating Entities with cdp_utility
Use the cdp_utility associate command to associate entities for JedAI metadata.
Usage:
cdp_utility associate <source_guid> <target_guid>
Example:
Assume one snapshot entity has the guid 161cac85-0bea-4098-a5a9- 17223b862a99*1 and a "test"
tag has the guid eb92e3d4-2a90-4a4b-8a8a- 1c2c3f092845*1. The following command associates
the tag to the snapshot:
cdp_utility associate 161cac85-0bea-4098-a5a9- 17223b862a99*1 eb92e3d4-2a90-4a4b-8a8a-
1c2c3f092845*1
Related Information
Appendix F: The cdp_utility Commands
Mount Operations with cdp_utility
A file interface for JedAI is provided through a mount point that supports standard filesystem
operations, such as reading and writing after an open() system call and ls, mkdir, and cp shell
operations. The mount point is only accessible by the current user, but the data stored in the mount
point follows filesystem permissions and is visible to any user across machines that also mount the
file interface.
Usage:
cdp_utility mount [<path>] [-u]
You must set the $CDNS_JEDAI_SERVER=file://<path> environment variable before using the
command. By default, JedAI uses the path set in this environment variable for mounting.
This command requires additional dependencies installed in the system to support FUSE:
fuse, fuse3, fuse-libs, and fuse3-libs.
To mount a file interface on an existing directory:
cdp_utility mount <path>
To list the current mountpoints or mounted paths for the current user:
cdp_utility mount
To unmount a file interface:
cdp_utility mount <path> -u
Related Information
Appendix F: The cdp_utility Commands
How Applications Use JedAI Data
Xcelium
WaveMiner
Semantic Diff
Xcelium
Xcelium has the capability to capture waveform data and store it in JedAI through the VWDB
interface. Run Xcelium with the following environment variables for each set of dumping
commands.
setenv CDNS_ENABLE_SHM2VWDB 1
setenv CDNS_XWD_CDB 1
setenv CDNS_XWD_MOZART SERVER $CDNS_JEDAI_SERVER
setenv CDNS_XWD_CDB_PATH
${CDNS_INST_DIR}/tools/lib/64bit/libvwdbc.so
setenv CDNS_XWD_MOZART_PATH $CDNS_JEDAI_PATH/libjedai.so setenv
CDNS_XWD_MOZART_AUTO_NAME 1
VWDB will directly stream into JedAI, and you can use the full hierarchical name to access it from
JedAI like you use vwdb files. Refer to the Creating a VWDB Probe Database section in Debugging
with Indago (on support.cadence.com) for more details on the Xcelium command usage.
WaveMiner
Setting the Environment
setenv CDNS_XWD_CDB 1
setenv CDNS_XWD_CDB_WAVEDIFF 1
setenv INDAGO_ROOT /grid/avs/install/indago/AGILE/latest setenv
INDAGO_DISABLE_DELETE_DESIGN_DB_INDICES 1
setenv INDAGO_LIBDAC_LOCATION
<$InstallDir/tools/lib/64bit/libdac.so> setenv CDNS_XWD_CDB_PATH
<$InstallDir/tools/lib/64bit/libvwdbc.so> setenv CDNS_JEDAI_PATH
<$InstallDir/tools.lnx86/jedAI/lib/64bit/>
setenv CDNS_JEDAI_SERVER <file://$HOME/vwdb_jedai> setenv CDS_LIC_FILE <port@server>
setenv LD_LIBRARY_PATH <LD_LIBRARY_PATH>
$installDir indicates where the tools are installed. CDS_LIC_FILE indicates where the license
server is, and LD_LIBRARY_PATH needs to include the path to the correct gnu C++ library (for
example, /grid/common/pkgs/gcc/v9.3.0p4/lib64) as well as include the path to
libcdsCommon_sh.so.
Running Xcelium
xrun +vwdb+shm2vwdb=1 -64 -sv testbench.v src/fifo.sv - lwdgen -input ida_probe.tcl -
access +rwc -clean - xmlibdirpath snapshots/old_snap –snapshot wm1
Storing the snapshots in JedAI
cdp_utility store snapshots/old_snap
cdp_utility store snapshots/new_snap
JedAI will return the full paths. For example:
/vols/datastore/snapshots/old_snap, /vols/datastore/ snapshots/new_snap
Running WaveMiner
WaveMiner needs to load the waveform data and blob data stored in JedAI before it starts running.
Namely, WaveMiner needs to load two Xcelium snapshots and two lists of waveform data for
comparison. The following command illustrates what types of data need to be gathered before
running:
verisium -waveminer-xmlibdirpath_golden
/vols/datastore/snapshots/old_snap -xmlibdirpath_new
/vols/datastore/snapshots/new_snap-wave_new
/vols/datastore/design1/run/bad-wave_golden
/vols/datastore/design2/run/good
/vols/datastore/snapshots/old_snap and /vols/datastore/snapshots/new_snap are full paths to
the snapshots parent directory, which are stored in JedAI as blob data, while
/vols/datastore/design1/run/bad and /vols/datastore/design2/run/good are stored in JedAI as
waveform data.
Semantic Diff
Setting the Environment
setenv CDNS_XWD_CDB 1
setenv INDAGO_ROOT /grid/avs/install/indago/AGILE/latest
setenv INDAGO_DISABLE_DELETE_DESIGN_DB_INDICES 1
setenv INDAGO_LIBDAC_LOCATION <$InstallDir/tools/lib/64bit/libdac.so>
setenv CDNS_XWD_CDB_PATH <$InstallDir/tools/lib/64bit/libvwdbc.so>
setenv CDNS_JEDAI_PATH <$InstallDir/tools.lnx86/jedAI/lib/64bit/>
setenv CDNS_JEDAI_SERVER <file://$HOME/vwdb_jedai>
setenv CDS_LIC_FILE <port@server>
setenv LD_LIBRARY_PATH <LD_LIBRARY_PATH>
$installDir indicates where the tools are installed. CDS_LIC_FILE indicates where the license
server is, and LD_LIBRARY_PATH needs to include the path to the correct gnu C++ library (for
example, /grid/common/pkgs/gcc/v9.3.0p4/lib64) as well as include the path to
libcdsCommon_sh.so.
Running Xcelium
xrun -64 -sv testbench.v src/fifo.sv -clean -xmlibdirpath snapshots/old_snap -snapshot
sd1
xrun -64 -sv testbench.v src/fifo.sv -clean -xmlibdirpath snapshots/new_snap -snapshot
sd1
This will generate two snapshots under different folders, old_snap and new_snap.
Storing the snapshots in JedAI
cdp_utility store snapshots/old_snap
cdp_utility store snapshots/new_snap
JedAI will return the full paths. For example:
/vols/datastore/snapshots/old_snap, /vols/datastore/ snapshots/new_snap
Running semantic_diff
Use the two paths collected in the last step and run semantic_diff on the two snapshots:
verisium -semanticdiff –xmlibdirpath_golden
/vols/datastore/snapshots/old_snap –xmlibdirpath_new
/vols/datastore/snapshots/new_snap –snapshot sd1
The Data Catalog is the central place for recording the meta data information of the JedAI system.
The Catalog includes the metadata for data, application, and support operations. On top of the
metadata that is stored, the Catalog provides a set of APIs for managing the metadata life cycle.
The Catalog component is currently used to manage the metadata of the dataset stored on the local
file system or NFS.
As shown in the diagram above, App, Project, Report, Model, Dataset, Dataobject, Schema,
and Feature are entities that are managed by the JedAI Catalog.
Tag and annotation can be used to annotate entities such as App, Project, Dataset, and so on.
A dataset needs to specify which apps can be run on top of it and thus needs to be associated
with app(s). Similarly, projects and reports run datasets on apps, and thus projects and reports
need to be associated with the combination of apps and datasets.
The Catalog keeps track of the history of changes in any entity. These changes are recorded
as different versions of the entity. You can then use different versions of an entity. For
example, you can create a project using the old version of data.
Schema and Feature are the underlying building blocks to track of the dataset's semantic.
Each dataset may refer to multiple data files corresponding to multiple schema, and each
schema is built on top of different features.
The Catalog also keeps track of machine learning models. For each version of a model, the
Catalog records the datasets that are to be part of the training.
The Catalog provides the API to enable you to search, explore, and annotate the Dataset,
App, Project, Report, Schema, and Feature entities.
As data comes in and out, the JedAI Catalog keeps track of the data lineage and audit history.
Related Information
Data Catalog Entities
Version-Awareness of Entities
REST API Usage
Defining and Using a Glossary
Blob Data Management
Data Catalog Entities
The metadata that is stored in the Data Catalog is organized as different entities, including Dataset,
Dataobject, Datasource, Schema, Feature, App, Project, Report, Tag, and Annotation. These
entities are described below.
Data Entities
Dataset         A set of data registered for a specific purpose or application. It may or may not
include more than one type of data. For example, an Innovus dataset may
contain more than 60 different types of data, such as pins, nets, wires, and so on,
which are referred as dataobjects.
Dataobject      A physical representation of one type of data. For example, pin data is one of 60
Innovus data types within a dataset. A dataobject is usually created during
dataset registration and profiling. The information regarding a dataobject can be
retrieved only as part of a specific dataset.
Datasource      A physical location for data that comes from outside JedAI. It is used only to
keep track of a simple data lineage where the data comes from outside of the
JedAI platform. It is usually provided during the data ingestion process.
Schema          A semantic representation of one type of data. It usually corresponds to one
dataobject and contains a list of features (attributes).
Feature         A representation of a column. It may also be referred as an attribute. It contains at
least the name and data type of the feature.
Profiling       An optional information that can be collected to represent a dataobject. Note that
profiling is not a standalone entity and is usually stored as part of a dataobject. It
may contain the size of disk files, number of records, number of columns for the
dataobject. For each attribute (feature) within a dataobject, the profile may
contain the number of distinct values, the number of null_value. For the numeric
data type, the profile may also contain the min, max, mean, median, 25%
quantile, 75% quantile, and so on.
Application Entities
App       An application that can be run on a dataset. The built-in apps, such as Timing Matrix,
PPA Compare, Heat Map, Silicon Sight, and Budget Analyzer, are pre-registered
within the Catalog. You can register your own apps through the API by uploading the
app's code.
Project   A project created by a user. It gathers the information of a list of datasets, along with
an app that can run on top of the datasets.
Report    A report that is generated from specific apps. A report is usually linked to datasets
and an app.
Model     A model that is generated from the machine learning process. It is usually linked to
datasets that participate in the training.
Entities for Supporting Operations
Tag           A tag can be attached to different entities to identify them easily. A tag can either
be part of a tag/value pair or simply a tag without a value. The tag itself is stored
as an entity so that it can be reused (associated) with different entities.
Annotation    An annotation is a longer text string that can be used to describe an entity. Both
tags and annotations are standalone entities that can be reused to be attached to
other entities. The difference between a tag and an annotation is that a tag can
be used as a key/value pair, while an annotation is a longer description.
Label         A label is a type of tag. However, a label is not a standalone entity; it is a part of
the entity and thus cannot be reused by any other entity (or even a different
version of the same entity).
Lineage       Represents the data lineage.
Audit         Records information on an entity's insert/update/delete/query activities.
Version-Awareness of Entities
In JedAI, entities include Dataset, Dataobject, Datasource, Schema, Feature, App, Project, Report,
Tag, and Annotation. Some of these entities, such as Dataset, Schema, and App, are version-
aware, which means their change history is retained in the Catalog. Other entities, such as
Dataobject, Datasource, Feature, Project, Report, Tag, and Annotation, are version-unaware,
which means their change history is not retained.
For consistency, each entity does have a version_id. However, for version-unaware entities,
the version_id is always 1.
Each entity is represented as a json object containing entity_id, version_id, and guid.
The entity_id is not unique among entities. Different versions of an entity will share the same
entity_id, but have different version_id.
A guid is used to identify each entity uniquely. It is a combination of the entity_id and
version_id, separated by an *. For example, a8e90ce3-169f-4840-8d81-77972d7e92c9*1 is
a guid that represents version 1 of the entity a8e90ce3-169f-4840-8d81-77972d7e92c9.
REST API Usage
Curl command to retrieve all apps through the Catalog API:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/app" -H                "accept:
application/json"
Corresponding python code to retrieve all apps through the Catalog API:
server = '10.8.49.61'
server_port = '5005'
catalog_url = "http://{catalog_node}:{catalog_port}/api".format(server,
server_port)
r = requests.get('%s/catalog/v1/app'%catalog_url, headers={'Content-Type':
'application/json'}).json()
Registering and Retrieving a Dataset
Creating and Retrieving a Schema
Creating and Retrieving a Feature
Registering and Retrieving an App
Creating and Retrieving a Tag
Creating and Retrieving an Annotation
Creating and Retrieving a Project
Creating and Retrieving a Report
Associating Entities
Searching for Entities
Getting Entity History
Deleting an Entity
Other Miscellaneous REST API
Tutorial
Registering and Retrieving a Dataset
Registering a new dataset
Creating a new version of a dataset
Profiling the data
Updating the dataset
Retrieving a dataset
Registering a new dataset
The parameters for registering a new dataset are described below:
apps                Optional      A list of apps (guid). The dataset needs to be associated with
apps. For each dataset, a list of apps on which it can be applied
needs to be included.
All datasets cannot be run on every app.
path                Required      Indicates the location where the dataset is stored.
name                Required      Indicates the dataset name.
design              Optional      Indicates the design name used for EDA tool.
run                 Optional      Indicates the run of the EDA data.
stage               Optional      Indicates the stage of EDA data generation.
status              Optional      Indicates the status of the dataset, such as starting,
registering, ingesting, profiling, active, and inactive. If not
provided, it will be set to active by default.
source_paths        Optional      Specifies a list of strings, each representing the path to the source
data.
owner               Optional      Specifies a string that indicates the owner of the dataset. If not
provided, the Catalog system records the user id of the person
calling the API as the owner.
description         Optional      Specifies a string describing the dataset.
labels             Optional      Specifies a list of label strings. It represents the labels that are to
be tagged on the dataset.
tags               Optional      Specifies a list of guids that represent the tags associated with the
dataset.
annotations        Optional      Specifies a list of guids that represent the annotations associated
with the dataset.
schemas            Optional      Specifies a list of guids that represent the schemas associated
with the dataset.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset"
-H "accept: application/json" -H "Content-Type: application/json"
-d ‘{"apps":["05afd4ec-9dbf-4fa1-8110-8be0bcc74be6*1", "bec33bcc-411f-4437-8b86-
7fc221841d33*1"],
"name": "cui_test", "description": "innovus", "design":"dsp", "owner": "jedai",
"path": "file:///opt/cadence/jedai/cui.db/16", "run":"",
"source_paths":["file:///tmp/data1", "file:///tmp/data2"],
"stage": "cts", "status": "active",
"tags":["016fec67-7628-4cc9-98c3-ba2d5cb03b23*1"]}’
Upon POST, the /dataset API is called.
If source_paths is provided, a list of datasource entities are created corresponding to the list
of paths included in the source_paths list.
If an Innovus dataset is used and subfolders exist in the path of the dataset, a list of
dataobject entities are created as part of the associated object for the dataset.
Creating a new version of a dataset
To create a new version of a dataset, use the POST option to provide the entity_id of the original
dataset, as well as the attributes that correspond to the new version of the dataset.
The following additional parameters may be used:
replace                 Optional    A Boolean value for updating a new version using the dataset
name. If an existing dataset name is used and replace:true, it
will create a new version of that dataset.
carry_association       Optional    A Boolean value to decide whether a new version carries over
the tag/annotation/app association from the old dataset
version. The default is true, which indicates that all the
tag/annotation/app associations will be carried over into the
new version of the dataset.
Other parameters are the same as for registering a new dataset.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset"
-H "accept: application/json" -H "Content-Type: application/json"
-d ‘{"apps":["05afd4ec-9dbf-4fa1-8110-8be0bcc74be6*1", "bec33bcc-411f-4437-8b86-
7fc221841d33*1"],
"carry_association":"true", "name":"cui_test", "description": "innovus",
"design": "dsp",
"entity_id": "675a937a-c39b-46c8-af6f-7b3cf369bb61", "owner": "jedai",
"path":"file:///opt/cadence/jedai/cui.db/16_1", "run":"",
"source_paths":["file:///tmp/data4","file:///tmp/data3"], "stage":"cts"}’
Profiling the data
Data profiling information is collected at the dataobject level. Provide the information as follows:
entity_id     Specifies the entity_id for the dataobject.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset"
-H "accept: */*" -H "Content-Type: application/json"
-d ‘{"entity_id":"675a937a-c39b-46c8-af6f-7b3cf369bb61","file_size":9320000,
"profile":[{"feature_type":"string","name":"from_path","null_count":0}],
"row_count":100,"schema":"05957d64-2ab9-4b6a-8124-
018f84bed493*1","version_id":1}’
Updating the dataset
To update an existing version of a dataset, use the PUT option to provide the entity_id and
version_id of the dataset, as well as the attributes that need to be changed.
Note that not all attributes can be updated in this PUT call. Those optional lists of associations,
such as apps and tags, can only be attached.
curl -X PUT "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset"
-H "accept: application/json" -H "Content-Type: application/json"
-d '{"entity_id":"46f18c9e-b01c-4c8c-a734-147c2ac18161",
"version_id":1,"description":"innovus","design":"dsp","name":"cui",
"owner":"jedai","path":"file:///opt/cadence/jedai/cui.db/lllll","run":"","stage":"cts
"}'
Retrieving a dataset
The /dataset API endpoint can be used to retrieve all the registered datasets in the Catalog or a
dataset with a specific entity_id.
To load all the registered datasets:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset"
-H "accept: application/json"
To load a dataset by specifying its entity_id and/or version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset?
entity_id=46f18c9e-b01c-4c8c-a734-147c2ac18161"
-H "accept: application/json"
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset?
entity_id=46f18c9e-b01c-4c8c-a734-147c2ac18161&version_id=1"
-H "accept: application/json"
Creating and Retrieving a Schema
Creating a Schema
Creating a new version of a schema
Updating the Schema
Retrieving a Schema
Creating a Schema
The parameters for creating a new schema are described below:
name        Required     Indicates the schema name.
features    Optional     Specifies a list of feature entries. Each feature entry in the list can be:
the guid of an existing feature in the Catalog.
a json object containing at least feature's name and feature_type. In
this case, a list of features will be created and then associated with
the schema.
Example 1
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/schema"
-H "accept: */*" -H "Content-Type: application/json"
-d ‘{"name":"wires","features":["61511f19-6b4f-4944-9a1c-adc2fe830268*1"]}’
Example 2
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/schema"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"features":[{"name":"id","feature_type":"integer"},
{"name":"from_pin","feature_type":"string"}],"name":"wires"}'
Creating a new version of a schema
To create a new version of a schema, use the POST option to provide the entity_id of the original
schema, as well as the attributes that correspond to the new version of the schema.
The following additional parameters may be used:
carry_association      Optional   A Boolean value to decide whether a new version carries over
the tag/annotation/app association from the old schema
version. The default is true, which indicates that all the
tag/annotation/app associations will be carried over into the
new version of the schema.
Updating the Schema
To update an existing version of a schema, use the PUT option to provide the entity_id and
version_id of the schema, as well as the attributes that need to be changed.
Note that associated attributes such as features cannot be updated in this PUT call.
curl -X PUT "http://{catalog_node}:{catalog_port}/api/catalog/v1/schema"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"entity_id":"61511f19-6b4f-4944-9a1c-adc2fe830268","version_id":1,
"description":"a new version of wire","name":"wire"}'
Retrieving a Schema
The /schema API endpoint can be used to retrieve all the registered schemas in the Catalog or a
schema with a specific entity_id.
To load all the registered schemas:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/schema"
-H "accept: application/json"
To load a schema by specifying its entity_id and version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/schema?
entity_id=e5b1c38e-8803-4c5a-aa54-a04fbe6d4781"
-H "accept: application/json"
(returns all versions)
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/schema?
entity_id=e5b1c38e-8803-4c5a-aa54-a04fbe6d4781&version_id=1"
-H "accept: application/json"
Creating and Retrieving a Feature
Creating a feature
The parameters for creating a new feature are described below:
name              Required     Indicates the feature name.
description       Optional     Specifies a string describing the feature.
feature_type      Required     Indicates the data type of the feature
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/feature"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"description":"unique id","name":"id","feature_type":"integer"}'
Updating a feature
To update an existing feature, use the PUT option to provide the entity_id and version_id of the
feature, as well as the attributes that need to be changed.
curl -X PUT "http://{catalog_node}:{catalog_port}/api/catalog/v1/feature"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"entity_id":"61511f19-6b4f-4944-9a1c-adc2fe830268","version_id":1,
"description":"unique id","name":"id","feature_type":"string"}'
Retrieving a feature
The /feature API endpoint can be used to retrieve all the registered features in the Catalog or a
feature with a specific entity_id.
To load all the registered features:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/feature"
-H "accept: application/json"
To load a feature by specifying its entity_id and version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/feature?
entity_id=61511f19-6b4f-4944-9a1c-adc2fe830268"
-H "accept: application/json"
(returns all versions)
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/feature?
entity_id=61511f19-6b4f-4944-9a1c-adc2fe830268&version_id=1"
-H "accept: application/json"
Registering and Retrieving an App
Registering an app in the Catalog
Creating a new version of an app
Updating an app
Retrieving an app from the Catalog
An app is a group of code that serves the purpose of business logic on datasets. You can develop
your own apps and register them in the Catalog. You can also develop applications through the
customized Dashboard. In JedAI, the Dashboard is considered as a special type of app that has
app_type set to dashboard.
Registering an app in the Catalog
When a customized app is developed, you need to make the JedAI system aware of this new app.
For this, you need to upload the customized JavaScript code into the system so that the Catalog
records the file's name and location, along with information of the app such as name, identifier, and
prefix. Refer to the Build Your Application Through Customized JavaScript section in Building
Customized Applications to learn how the file can be uploaded and the app API is called.
The parameters for registering a new app are described below:
name             Required    Indicates the app name. Duplicate app names are not allowed.
identifier       Required    Is usually an abbreviation of the app name. It needs to be a single
word for easy handling.
namespace        Optional    Usually indicates who developed the app. The namespace for
preloaded apps is recorded as cadence.
url              Optional    Indicates where the code is stored and its file name. The file is the
customer build web application in JavaScript.
To view the detailed steps for registering an app through the Web
interface, see the Build Your Application Through Customized
JavaScript section.
app_type         Optional    Can be set to dashboard when a new dashboard is registered.
Refer to the Build Your Application Through Customized JavaScript
section for details on how a dashboard can be used to build
customized application.
labels           Optional     Specifies a list of label strings. It represents the labels that are to be
tagged on the app.
annotations      Optional     Specifies a list of guids that represent the annotations associated
with the app.
An example of the app registration curl command is shown below:
curl -X POST " http://{catalog_node}:{catalog_port}/api/catalog/v1/app " -H                    "accept:
*/*" -H "Content-Type: application/json" -d '{"identifier":"sample-
app","name":"Sample App","url":"sampleApp.js"}'
Creating a new version of an app
To create a new version of an app, use the POST option to provide the entity_id of the original
app, as well as the parameters that correspond to the new version of the app.
The following additional parameter may be used:
carry_association      Optional     A Boolean value to decide whether a new version carries over
the tag/annotation association from the old app version. The
default is true, which indicates that all the tag/annotation
associations will be carried over into the new version of the
app.
Updating an app
To update an existing app entity, use the PUT operation to provide the entity_id and version_id of
the app in the json object.
Retrieving an app from the Catalog
The /app API endpoint can be used to retrieve all the registered apps in the Catalog or an app with
a specific entity_id.
To load all the registered apps:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/app"
-H "accept: application/json"
To load an app by specifying its entity_id and/or version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/app?
entity_id=91322f39-8b7e-3924-8a1c-adc2fe830268"
-H "accept: application/json"
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/app?
entity_id=91322f39-8b7e-3924-8a1c-adc2fe830268&version_id=1"
-H "accept: application/json"
Creating and Retrieving a Tag
Creating a tag
The parameters for creating a new tag are described below:
name              Required   Indicates the tag name.
description       Optional   Specifies a string describing the tag.
value             Optional   Specifies a value for the tag.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"description":"innovus description","name":"innovus"}'
Updating a tag
To update an existing tag, use the PUT option to provide the entity_id and version_id of the tag.
curl -X PUT "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"entity_id":"46f18c9e-b01c-4c8c-a734-147c2ac18161","version_id":1,
"description":"innovus description","name":"innovus","value":"dsp"}'
Retrieving a tag
The /tag API endpoint can be used to retrieve all the registered tags in the Catalog or a tag with a
specific entity_id.
To load all the registered tags:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag"
-H "accept: application/json"
To load a tag by specifying its entity_id and/or version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag?
entity_id=46f18c9e-b01c-4c8c-a734-147c2ac18161"
-H "accept: application/json"
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag?
entity_id=46f18c9e-b01c-4c8c-a734-147c2ac18161&version_id=1"
-H "accept: application/json"
Creating and Retrieving an Annotation
Creating an annotation
The parameters for creating a new annotation are described below:
annotation      Required    A simple text.
name            Optional    Indicates the annotation name.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/annotation"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"annotation":"innovus"}'
Retrieving an Annotation
The /annotation API endpoint can be used to retrieve all the registered annotations in the Catalog
or an annotation with a specific entity_id.
To load all the registered annotations:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/annotation"
-H "accept: application/json"
To load an annotation by specifying its entity_id and/or version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/annotation?
entity_id=e22be607-355f-4afd-9a15-c2b670903928%2A1"
-H "accept: application/json"
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/annotation?
entity_id=e22be607-355f-4afd-9a15-c2b670903928%2A1&version_id=1"
-H "accept: application/json"
Creating and Retrieving a Project
A project is a logic entity that integrates datasets and apps together. Once a project is created and
opened, the backend engine will extract the app that is associated with the project and apply the
app's function on the datasets associated with the project.
Creating a project in the Catalog
The parameters for creating a new project are described below:
apps             Required     Indicates the guid of the app on which this project will be applied.
datasets         Required     Indicates the guid(s) of the datasets on which this project will be
working.
name             Required     Indicates the project name. The project name should be unique.
labels           Optional     Specifies a list of label strings. It represents the labels that are to be
tagged on the project.
tags             Optional     Specifies a list of guids that represent the tags associated with the
project.
annotations      Optional     Specifies a list of guids that represent the annotations associated
with the project.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/project"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"apps":["bec33bcc-411f-4437-8b86-7fc221841d33*1"],
"datasets":["46f18c9e-b01c-4c8c-a734-147c2ac18161*1"],
"name":"timing-matrix","visible":"true"}'
Retrieving a project from the Catalog
The /project API endpoint can be used to retrieve all the registered projects in the Catalog or a
project with a specific entity_id.
To load all the registered projects:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/project"
-H "accept: application/json"
To load a project by specifying its entity_id and/or version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/project?
entity_id=75de6653-74d8-4123-b7e7-7edce2654769"
-H "accept: application/json"
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/project?
entity_id=75de6653-74d8-4123-b7e7-7edce2654769&version_id=1"
-H "accept: application/json"
Creating and Retrieving a Report
A report can be generated from a specific app, and is usually linked to datasets and an app.
Creating a report in the Catalog
The parameters for creating a new report are described below:
apps              Required     Indicates the guid of the app on which this report will be applied. As
of now, only one app is allowed.
datasets          Required     Indicates the guid(s) of the datasets on which this report will be
working.
url               Optional     Indicates where the report will be stored.
report_type       Required     Indicates the type of the report.
name              Optional     Indicates the report name.
labels            Optional     Specifies a list of label strings. It represents the labels that are to be
tagged on the report.
tags              Optional     Specifies a list of guids that represent the tags associated with the
report.
annotations       Optional     Specifies a list of guids that represent the annotations associated
with the report.
Retrieving a report from the Catalog
The /report API endpoint can be used to retrieve all the registered reports in the Catalog or a
report with a specific entity_id.
To load all the registered report:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/report"
-H "accept: application/json"
To load a report by specifying its entity_id and/or version_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/report?
entity_id=8d9c4ea7-2e0c-48ef-b1e0-77968120d076"
-H "accept: application/json"
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/report?
entity_id=8d9c4ea7-2e0c-48ef-b1e0-77968120d076&version_id=1"
-H "accept: application/json"
Associating Entities
To associate one entity with another entity, you can use the /entity_association API endpoint in a
POST operation as shown in the following example.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/entity_association"
-H "accept: */*" -H "Content-Type: application/json"
-d '[{"operation":"add","source":"57cf9f98-fbb4-42df-95cd-eb5092cd12b6",
"target":"3254025c-61ea-4cae-b76e-98c297bd7a30"}]'
The /entity_association API endpoint can be used to both store new associations and delete
existing associations between a list of entity pairs.
Searching for Entities
You can use the /entity_search API endpoint search for any entity by providing a keyword.
The following options can be used to narrow the returned result:
keyword       Optional     Specifies the words used to search, separated by space.
Default: No
history       Optional     Indicates whether to return all versions of the entity. If set to false, only
the current version of the entity is returned.
Default: true
type          Required     Searches only for the specified entity type. Choose from dataset, app,
project, tag, and so on.
filter_by     Optional     Specifies a list of filter conditions.
For each object (condition) within the list, it is a conjunction (and).
Within each object, it contains two attributes: conjunction (and/or)
and conditions (a list of object/conditions).
For each condition, it contains three attributes: key, value and op.
The op can be any of operation in ["=", "!=", ">", "<", ">=", "<=",
"contains", "not contains", "startwith", "endwith"].
sorted_by       Optional   Specifies a list of objects, with each object containing the key and
order (asc or desc) so that the result returned will be sorted.
limit           Optional   Indicates the number of records that will be returned as a batch.
offset          Optional   Indicates the starting record of the batch.
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/entity_search"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"sorted_by":[{"key":"design","order":"ASC"},
{"key":"stage","order":"DESC"}],
"filter_by":[{"conjunction":"or","conditions":
[{"key":"tag","value":"new_tag","op":"="},{"key":"tag","value":"tag1","op":"="}]}],
"keyword":"data","type":"dataset"}'
Examples:
1. Search for all datasets:
curl -X POST "http://{catalog_host}:{catalog_port}/api/catalog/v1/entity_search" \
-H "accept: */*" -H "Content-Type: application/json" \
-d '{"type":"dataset"}'
2. Search for datasets that have project name as project1:
curl -X POST "http://{catalog_host}:{catalog_port}/api/catalog/v1/entity_search" \
-H "accept: */*" -H "Content-Type: application/json" \
-d '{"type":"dataset",\
"filter_by": [{"key":"project","op":"=","value":"project1"}] \
}'
3. Search for datasets that have project name as project1 and design name not equal to
design1:
curl -X POST "http://{catalog_host}:{catalog_port}/api/catalog/v1/entity_search" \
-H "accept: */*" -H "Content-Type: application/json" \
-d '{"type":"dataset", \
"filter_by": [ \
{"key":"project","op":"=","value":"project1"}, \
{"key":"design","op":"!=","value":"design1"} \
] \
}'
4. Search for datasets that have either project name as project1 or design name as design1:
curl -X POST "http://{catalog_host}:{catalog_port}/api/catalog/v1/entity_search" \
-H "accept: */*" -H "Content-Type: application/json" \
-d '{"type":"dataset", \
"filter_by": [ \
{"conjunction":"or",
"conditions":[
{"key":"project","op":"=","value":"project1"}, \
{"key":"design","op":"=","value":"design1"} \
] \
} \
] \
}'
5. Search for datasets containing UM files in project1:
curl -X POST "http://{catalog_host}:{catalog_port}/api/catalog/v1/entity_search" \
-H "accept: */*" -H "Content-Type: application/json" \
-d '{"type":"dataset", \
"filter_by": [ \
{"conjunction":"and",
"conditions":[
{"key":"project","op":"=","value":"project1"}, \
{"key":"include_um","op":"=","value":"true"} \
] \
} \
] \
}'
Getting Entity History
To get all version history, the /entity_history API endpoint can be used. Specify the entity_id to
retrieve all version of an entity, as shown below.
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/entity_history?
entity_id=46f18c9e-b01c-4c8c-a734-147c2ac18161"
-H "accept: */*"
Deleting an Entity
The /entity API endpoint can be used to delete a specific entity.
To delete the current version of the entity with the specified entity_id:
curl -X DELETE "http://{catalog_node}:{catalog_port}/api/catalog/v1/entity?
entity_id=46f18c9e-b01c-4c8c-a734-147c2ac18161"
-H "accept: */*"
To delete all version of the specified entity, set delete_allto true:
curl -X DELETE "http://{catalog_node}:{catalog_port}/api/catalog/v1/entity?
entity_id=05dd5e95-f107-4e10-8de5-8565a1a55a2f&delete_all=true"
-H "accept: */*"
Other Miscellaneous REST API
Audit
The JedAI platform keeps track of the write or update operations for each entity. Therefore, the
operation history of an entity can be retrieved through the API by specifying the entity's guid, as
shown below.
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/audit?guid=46f18c9e-
b01c-4c8c-a734-147c2ac18161*1"
-H "accept: */*"
Lineage
The data lineage is recorded for dataset movement. It can also be retrieved by specifying the
entity's guid.
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/lineage?
guid=46f18c9e-b01c-4c8c-a734-147c2ac18161*1"
-H "accept: */*"
Tutorial
Suppose you want to add a simple generic dataset into the Catalog. The commands below shows
the steps for adding the dataset, querying the dataset, adding a tag to the dataset, and searching
the dataset based on the tag.
The following steps are based purely on the REST API.
Add a dataset:
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset"
-H "accept: application/json" -H "Content-Type: application/json"
-d '{"description":"a sample dataset for tutorial","name":"example1",
"path":"/opt/cadence/jedai/sample_data/user_data/user2.txt",
"label":"tutorial, random"}'
Query a dataset based on entity_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/dataset?
entity_id=57cf9f98-fbb4-42df-95cd-eb5092cd12b6"
-H "accept: application/json"
Associate a tag to the dataset.
Create the tag:
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag"
-H "accept: */*" -H "Content-Type: application/json"
-d '{"description":"generic data","name":"generic"}'
Query the tag to get the entity_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag"
-H "accept: application/json"
Associate the tag to the dataset:
curl -X POST "http://{catalog_node}:
{catalog_port}/api/catalog/v1/entity_association"
-H "accept: */*" -H "Content-Type: application/json"
-d '[{"operation":"add","source":"57cf9f98-fbb4-42df-95cd-
eb5092cd12b6*1",
"target":"3254025c-61ea-4cae-b76e-98c297bd7a30*1"}]'
Get the dataset based on the tag with entity_id:
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/tag?
entity_id=3254025c-61ea-4cae-b76e-98c297bd7a30"
-H "accept: application/json"
Defining and Using a Glossary
You can define a glossary entity in the catalog and ingest the dataset with the glossary.
Project: A collection of design, verification activities, along with their associated data, focused
on a specific goal. ​
Design: The design being tested or the layout.​
Design Version: A specific iteration or revision of a design, capturing changes and updates
made to the design.
Phase (verification)/Snapshot: A capture of a design's state during the development
process. A stable version to be tested for a phase, such as pre-route or post-route.
Run tag: A unique identifier for a specific run or execution of a process, such as a simulation
run, a regression test, or multiple runs of the implementation process.
Scenario: User-defined test cases or situations that represent real-world conditions or
requirements, allowing validation and optimization of designs.​
Dataset: A collection of related data, such as design files, constraints, and layout information,
simulation results, test vectors.​
Dataobject: An individual piece of data or file within a dataset. This can be a component, a
constraint in the design, a specific test vector, a simulation result, a test-bench configuration,
or a log file.​
Tag: User-defined labels or keywords for organizing and categorizing data, enabling easy
search and retrieval of related design files, test results, or constraints.
Example to query the dataset:
1. Search the dataset containing UM files in project1:
curl -X POST "http://{catalog_host}:{catalog_port}/api/catalog/v1/entity_search"
\
-H "accept: */*" -H "Content-Type: application/json" \
-d '{"type":"dataset", \
"filter_by": [ \
{"conjunction":"or",
"conditions":[
{"key":"project","op":"=","value":"project1"}, \
{"key":"include_um","op":"=","value":"true"} \
] \
} \
], \
"sorted_by": [​\
{​"key": "project",​\
"order": "asc"​},​ \
{​"key": "design", ​\
"order": "desc"​}​ \
] \
}'
2. Ingest the dataset with glossary:
curl -X 'POST' http://{catalog_host}:
{catalog_port}/api/analytics/sessions/default/dataset/v1/ingest
-H 'accept: application/json'
-H 'Content-Type: multipart/form-data'
-F 'file=@{user_dir}/metrics.json.smpl.json;type=application/json'
-F 'project=example'
-F 'design=example'
-F 'flow_phase=default'
-F 'scenario=scenario_1'
-F 'runtag=cerebrus'
-F 'design_version=22.10'
-F 'overwrite=false'
-F 'add_to_exist=true'
curl -X 'POST' http://{catalog_host}:
{catalog_port}/api/analytics/sessions/default/dataset/v1/register
-H 'accept: application/json'
-H 'Content-Type: application/json'
-d '{"args": {"dataset_id":"c06b6adf-31a7-4f2d-9402-47b5f19fad28*1",
"tags":"Cerebrus", "hidden": true}}'
Blob Data Management
Uploading Blob Data
Updating the Metadata of the Blob Data
Searching the Metadata of the Blob Data
Deleting Blob Data
Retrieving or Downloading Blob Data
Uploading Blob Data
The parameters for uploading blob data are described below:
file       Required    Indicates the binary data of the blob data.
name       Optional    Indicates the name of the blob data. If not specified, use the filename of the
blob data.
user      Optional   Indicates the user who uploaded the file.
Example (bash)
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/blob"
-F name=test.txt -F file=@/path/to/test.txt -F user=foo
Example (python)
import requests
with open("/path/to/test.txt", "rb") as fd:
files = {"file": ("test.txt", fd.read())}
resp = requests.post(f"{catalog_node}:{catalog_port}/api/catalog/v1/blob",
data={"name": "test.txt", "user": "foo"},
files=files)
Updating the Metadata of the Blob Data
The parameters for updating the blob data are described below:
entity_id      Required   Indicates the entity id of the blob data in the catalog.
version_id     Optional   Indicates the entity version of the blob data in the catalog. If not
specified, use 1.
Example
curl -X PUT "http://{catalog_node}:{catalog_port}/api/catalog/v1/blob"\
-H 'accept: */*' \
-H 'Content-Type: application/json' \
-d '{
"entity_id": "c0de2de3-6e42-41a7-a168-2d68baf6ff73",
"version_id": 1,
"usage": "test"
}'
Searching the Metadata of the Blob Data
You can search the metadata of a blob using the /entity_search endpoint.
Example
curl -X POST "http://{catalog_node}:{catalog_port}/api/catalog/v1/entity_search"\
-H 'accept: */*' \
-H 'Content-Type: application/json' \
-d '{
"filter_by": [ {"key": "name", "op": "=", "value": "test.txt"} ],
"type": "blob"
}'
Deleting Blob Data
The parameters for deleting blob data are described below:
entity_id    Required    Indicates the entity id of the blob data.
Example
curl -X DELETE "http://{catalog_node}:{catalog_port}/api/catalog/v1/blob?
entity_id=c0de2de3-6e42-41a7-a168-2b68baf6ff73"
Retrieving or Downloading Blob Data
The parameters for retrieving the metadata and downloading blob data are described below:
entity_id     Required     Indicates the entity id of the blob data.
version_id    Optional     Indicates the version of the blob data.
download      Optional     Indicates whether or not to download the content of the blob data
(true/false).
Example (bash)
curl -X GET "http://{catalog_node}:{catalog_port}/api/catalog/v1/blob?
entity_id=c0de2de3-6342-41a7-a168-2b68baf677f3&version_id=1&download=true"
Example (python)
import requests
resp = requests.get(f"{catalog_node}:{catalog_port}/api/catalog/v1/blob",
params={"entity_id": "c0de2de3-6342-41a7-a168-2b68baf677f3",
"version_id": 1,
"download": True})
with open("test.txt", "wb") as file:
file.write(resp.content)
Data Extraction, Ingestion, Registration, Profiling and Retrieval

---
## Data Extraction

, Ingestion, Registration, Profiling and Retrieval
Data Extraction, Ingestion and Registration
Extracting Data from Genus, Innovus, and Tempus
Extraction with write-dataset
Extraction with Customized TCL Scripts
Data Ingestion and Registration on JedAI
Sample Data
Ingesting and Registering Data Using the Command Line
Ingesting and Registering Data Using the REST API
Tutorials
Data Encoding
Reading Data After Registration
Identifying the Published Path
Reading the Dataset with the Published Path
Data Profiling
Data Querying
Data Retrieval
DataSet
FileSystem

---
## Monitor Dashboard

The JedAI Monitor Dashboard application can be used to visualize the metric data generated from
Innovus and Cerebrus. The metrics file is extracted together with the db data after running the
JedAI write-dataset command. You can then ingest and register the whole dataset into the JedAI
platform.
Creating a Monitor Dashboard
Editing a Dashboard
Understanding and Using a Monitor Dashboard
Checking Eligible Metric Datasets and Attributes
Checking Filter Templates
Filtering Datasets
QOR Summary Page
Project Summary Comparison Page
Metrics Comparison Page
Project Detail Page
Analysis Report Page
Creating a Monitor Dashboard
1. Click Dashboards on the sidebar to view or delete existing dashboards and create a new
monitor dashboard.
2. Click the Create Dashboard button to create a new dashboard.
3. The New Dashboard screen shows all the metrics dataset that can be visualized in the JedAI
monitor dashboard. To view the metrics file extracted from Innovus, select the Default radio
button under Dashboard Template.
4. Add filter conditions to the table columns. These filter conditions are later used to get the
target datasets and then render the dashboard. This means you do not need to create a new
dashboard each time you ingest new metrics files. The new files will be automatically added
into the existing dashboard by the filter conditions.
Editing a Dashboard
Cloning a dashboard: To clone an existing dashboard, select it and click Clone Dashboard.
Changing config settings: To change the config settings of an existing dashboard, click the "+"
symbol next to the dashboard name. This opens the Edit Dashboard screen. Here, edit the
existing config settings as required and click Apply.
Renaming a dashboard: To rename an existing monitor dashboard, open Edit Dashboard and
enter a new name in the Name field.
Understanding and Using a Monitor Dashboard
Checking Eligible Metric Datasets and Attributes
Click the + button to get more information about eligible metric datasets for a dashboard.
In the resulting Dashboard Information page:
The Dataset List section shows all the eligible metrics datasets filtered by filter conditions.
You can select the ones you want to show in the dashboard.
The Metrics section shows all the available attributes for metric datasets. You can select the
ones you require to show in the dashboard. By default, the following four metrics are shown:
timing.setup.tns, timing.hold.tns, design.congestion.hotspot.total,
and design.density.
Checking Filter Templates
Click the     to view all the filter templates and apply a saved template to the dashboard.
Whenever you change the settings inside a dashboard, such as changing the metrics filter, design
filter, or table configuration, all of these dashboard filters can be saved as templates. This way, even
when multiple users edit the same dashboard together, one of them can easily find the template he
or she created before and share its settings with another user.
You can select any template to preview its settings and click APPLY to apply its settings to the
dashboard.
Filtering Datasets
You can filter the datasets showed in the dashboard by using the four selection boxes. These filters
will based on the datasets selected from the Dashboard Information page.
Place the cursor on the title of a selection box to view all selected items.
QOR Summary Page
The QOR Summary page shows the overall values for each flow phase on the selected metrics for
all datasets.
For each project, the QOR Summary page shows the "sum" values for all designs.
If you need to change the order of the flow phases, you can do so by changing the order of the
phase columns in the summary table​.
The page shows the value for the root snapshots in default. Click the snapshot name (link) to
view the result for its child snapshots.
Besides the selected metric, the page also shows the applications that were run for this
dataset. Click a check mark to view the corresponding analysis report. For example, for
Congestion Analyzer, place the mouse on the check mark to preview the congestion scores
for each layer. This will help you decide whether or not to see the detailed report.
Click the   icon to change the table configuration for each metric.
Any value that exceeds the threshold will be colored red.
Project Summary Comparison Page
The Project Summary Comparison page shows the project "sum" value comparison for each metric.
Metrics Comparison Page
The Metrics Comparison page enables you to display a customized table and graph based on the
selected metrics.
To view the metrics comparison, define your custom columns:
1. Click the + symbol next to Customized Columns.
​
Note
JedAI provides two default customized columns, SDC and speed.
You can configure or delete these columns, if required.
2. Specify the name for the new column.
3. Add the definition or the column. The definition should be the functioning format.
4. To display the customized graph, select x and y from the table columns. For example, you can
choose area, power, or speed to check the tradeoff.
Project Detail Page
The Project Detail page compares the different designs for each project for multiple fields.
Analysis Report Page
The Analysis Report page shows the saved reports from different applications for each dataset.
Note this tab is only if you have saved some reports while running applications for the select
datasets.
1. Select a metric dataset.
2. For each dataset, the report contains different snapshots with different parameter settings in
the application project.
Data Exploration and Superset Dashboard

---
## Data Exploration

Building the Dashboard in Superset
1. If any data is registered in the Catalog, a spark_hive_db entry is listed on the Superset
database, which is accessible from the Data menu page.
2. From the Data menu, click Dataset and + DATASET, and then select spark_hive_db. The
SCHEMA list will show all the datasets registered in Catalog.
3. Choose the dsp_cts schema as an example:
4. Click base_cells and go to the Exploration page.
5. Click RAW RECORDS.
6. Under COLUMNS, select the columns you want to check.
7. Click RUN QUERY to see the result.
Building the Dashboard in Superset
Trim the tables you want to store in the database as Superset cannot support too much data. The
recommendation is to limit the result or choose a part of columns.
1. Connect the databases to Superset.
a. Go to databases list. URL: http://{server}:{port}/databaseview/list/
b. Click + DATABASE to connect a new database to Superset, support SQLite, hive,
PostgreSQL, and so on.
After JedAI installation, there will be two example dbs in the Superset platform:
jedai_example and examples.
2. Upload the data into the Superset Platform. You can use one of the following upload methods:
Use the upload feature from Superset: http://{server}:
{port}/csvtodatabaseview/form
a. Choose the file you want to upload and the target database (added to the platform
in the Step 1) to which you want to upload data.
b. Make sure the target database to which you want to upload data has Allow data
upload selected.
Upload data with Python for any kind of DataFrame.
a. Connect to the database in python and store data in it.
b. Then go to the Datasets page (http://{server}:
{port}/tablemodelview/list/) and click +DATASET to add the table.
3. Build the chart for the required dataset.
See the table below for explanation of the red highlighted sections.
1   Choose the required dataset to build a chart. Edit the dataset using Edit Dataset.
2   Specify the dataset information: metrics, columns, and so on using the tabs in the Edit
Dataset form.
3   Choose the visualization type.
4   Specify the query conditions.
5   Displays the visualization result.
6   Displays the SQL result.
7   Displays the raw data.
Click SAVE at the top of the form to save this query into Charts.
4. Create and change the dashboard:
a. Go to the following URL:
http://{server}:{port}/dashboard/list/
b. View the sample dashboards
c. Build a dashboard with the related charts.
5. Query data in SqlLab. Go to the following URL:
http://{server}:{port}/superset/sqllab
See the table below for explanation of the red highlighted sections.
1   Write SQL code here for doing calculations.
2   Preview the result of the SQL code.
3   Use EXPLORE to save the result as a dataset into the target database.

---
## Notebook

To open Notebook:
Click the Jupyter Notebook icon on the Home page of the Web server.
OR
Type the URL http://{server}:{port}/ in your browser, replacing {server} and {port} with
the corresponding strings recorded during the installation.
You can log into Notebook using {any_username}/Cadence! as username/password.
After logging in, you can run the standard Jupyter notebook.
A list of tutorials is pre-loaded under the tutorial folder to demonstrate the use of different
components of the JedAI system.
Among these tutorials:
01_Data_Registration demonstrates the steps for ingesting and registering a dataset in
JedAI.
02_Catalog demonstrates the simple operations that you can perform with the Catalog.
03_jedai_widgets shows some simple widgets that are used in JedAI.
04_Basic_Calculation_Engine and 05_dashboard_develop_example are two notebooks to
demonstrate how you can develop customized applications. Check the Building Customized
Applications section for details.
Notebooks 06_Application_* to 12_Application_* demonstrate how each of these
applications are developed using the Python APIs for the Analytics engine.
Analytic Engine and App Server

---
## Analytic Engine

and App Server
App Server
General APIs
Application-specific APIs
Python APIs for Analytics Engine
Catalog
Data Manipulation APIs
Application-specific APIs

---
## Pipeline and Workflow

Pipeline and workflow are JedAI's no-code and low-code solutions, respectively, for data
Extraction, Transformation, and Loading (ETL). You can manipulate the pipeline and workflow
using the Flows tab in JedAI.
Creating a Flow
Defining the Pipeline
Defining the Workflow
Creating a Flow
To create a flow:
1. Click the Create Flow button on the Flows tab.
2. In the Add New Flow form, specify the name and type of the flow. Type can be either pipeline
or workflow, as required.
3. Optionally, in the Upload Json section, you can upload an existing Json file to load the
pipeline or workflow from that file.
The sample json file shown below represents the meta data of the pipeline/workflow:
{
"graph": {
"processes": {},
"connections": [
],
"metainfo": {
"samplePercentage": "0.1",
"seed": "22000",
"name": "timing_matrix",
"type": "pipeline"
},
"config": {
"spark_properties": {
"config": {
"spark.default.parallelism": "24",
"spark.driver.memory": "1g",
"spark.executor.cores": "2",
"spark.executor.instances": "2",
"spark.executor.memory": "1g",
"spark.sql.shuffle.partitions": "24"
},
"master": "yarn"
}
}
}
}
Two json examples can be found at:
a. flow_services/data_pipeline_engine/config/timing_matrix_config.json
b. flow_services/workflow_engine/config/interposer_config.json
Defining the Pipeline
A pipeline represents the no-code ETL process. In general, a pipeline is represented as a series of
nodes along with the links among them.
The sample piping interface below for creating a Timing Matrix is loaded from
flow_services/data_pipeline_engine/config/timing_matrix_config.json​.
The top right of the screen provides the following three icons:
download json      - Used to edit and download a json file.
run with sample data      - Used to run the pipeline on a small sample dataset.
run with complete data     - Used to run the pipeline on the real dataset.
To define a pipleline:
1. Choose a node type from the choose node type and drag section.
The following two node types are available:
Input node: Only has an output handle.
Default node: Has both input and output handles and can be used for the following
functions:
Filter
Join
Window Function
New Column
Drop Column
Rename Column
2. Drag the chosen node type to the canvas:
a. To define an input node:
a. Drag and drop an input node on to the canvas, as shown below.
b. Choose the type of input data – PARQUET, CSV, or JSON.
c. Specify the location of the file.
d. Specify the columns of the data.
e. Click APPLY.
b. To define a default node:
a. Drag and drop the node.
b. Use the join operator as shown in the example below.
Choose columns from left and right side respectively by clicking +.
Click the trash icon to delete a column.
Specify the type of join (inner, outer etc.) and join condition, then click
APPLY.
c. The example below shows the filter operation on the table:
3. Add and edit additional nodes as required:
Choose a node type and drag and drop it on the canvas.
To link two nodes, point to the right point of the "from" node and then click and drag a
line to the left point of the "to" node, making sure to press and release the mouse button
only when "+" is appearing.
To delete a node, click it and then press the backspace key on the keyboard. The node
and its related links will be deleted.
4. Once all the nodes are set up, you can set up the configuration as shown in the example
below.
5. Next, run the code on the Analytic engine by clicking the              or   icon at the top-right corner.
6. After running the pipeline, you will see whether it is success in the result at the upper-right
corner. If there is an error, a pipeline error pop-up is displayed. You can view the details by
clicking the Error Log tab, as shown below.
Defining the Workflow
A workflow represents the low-code ETL process. Workflow supports python and bash scripts.
Creating a workflow is similar to creating a pipeline, except that you choose workflow as the flow
type.
Defining a workflow is a little different from defining a pipeline. As shown below, you can define a
workflow through the interface.
At the top of the screen, you can choose one of the following three types of nodes: Prepare, Step,
and Validate. A node in the workflow can be defined using a python or bash script.
Prepare: Prepare something for the main step.
Step: Execute the main step.
Validate: Validate the code for the main step.
At the top-right corner, there are two clickable icons:
download json file
run workflow
Creating, Linking, or Deleting Nodes
Choose a node type and drag and drop it on the canvas.
To link two nodes, point to the right point of the "from" node and then click and drag a line to
the left point of the "to" node, making sure to press and release the mouse button only when
"+" is appearing.
To delete a node, click it and then press the backspace key on the keyboard. The node and its
related links will be deleted.
To delete a link between two nodes, click the cross on the connecting line.
Editing the Code for a Node
Two kinds of parameters are passed to the workflow – one for the whole flow config and the other
for passing between tasks.
The WORKFLOW_BIN, WORKFLOW_HOME, WORKFLOW_MODE, WORKFLOW_SCHEDULER, and WORFLOW_URL
values are predefined. No need to change them.
You need to customize only the following parameters:
WORKFLOW_RUN_HOME: Specify the directory where you want to start the run.
WORKFLOW_RUN_TAG: Specify the tag for the run.
WORKFLOW_RUN_VAR: Specify the data_path in key-value format.
Getting configuration values:
Use conf["run_home"] to get the value of WORKFLOW_RUN_HOME.
Use conf["tag"] to get WORKFLOW_RUN_TAG.
Use conf["variables"] to get WORKFLOW_RUN_VAR. In the python code below, lines 4-7
use the data_path defined in WORKFLOW_RUN_VAR before.
Note: For the bash shell script, use $run_home/$tag/$variables to get the
corresponding config values.
Use Variable to store the result of a step and get it in another step. In the python code
below, entity_id is passed from the Register_1 step to the Profile_1 step.
Once all the nodes are set up, you can set up the configuration (see below).
You can then run the code on the Analytic engine by clicking the              or   icon at the top-right corner.
The workflow supports a limited LSF mode even if the JedAI server was launched on a non-lsf
machine. If the JedAI server machine can bsub lsf jobs, no need to change the settings.
"WORKFLOW_LSF_MODE": "remote",
"WORKFLOW_LSF_URL": "http://vlsj-mozart-poc1:22223",
Once you add the above setting, the JedAI server can bsub the job to an LSF machine even if the
JedAI server was installed on a non-lsf machine, such as on a docker or a k8s cluster.
Workflow Example for Running Innovus
JedAI provides a sample workflow, named example_workflow_innovus, for using the workflow to run
Innovus. In this example, JedAI shows how to use lsf to run the foundation flow FF_tdsp.tar.gz.
The license and WORKFLOW_RUN_HOME should be set in the workflow configuration. Here,
WORKFLOW_RUN_HOME specifies the directory where you placed the foundation flow.
The workflow contains six steps. In each step, use bsub to run the Innovus tcl command.

---
## Building Customized Applications

With JedAI, you can build customized applications:
Using Customized JavaScript
Using the Customized Dashboard Template
Developing a Customized App
Using Customized JavaScript
You can create your own custom Web app, without depending on the Cadence team, and upload it
using JedAI's Register feature. This is a two-step process:
1. Create your own app or remote component using the provided framework (Paciolan).
2. Upload the final built app or remote component to JedAI using the Register feature.
To build a customized Web application, you might need to create your own REST API and back-
end calculate engine to manipulate the data, create customized JS for the front-end interface, and
then register the application with the JedAI system. To create Analytic REST API/back-end
calculate engine, you can use Notebook to build business logic and expose REST API endpoint for
the customized Web application.
For other part of the customized web application, below is the demonstration how you can create
their own apps (remote component) using the Cadence Web developer studio, register it with the
JedAI platform and can start using the app dynamically without any restart/redeployment of the
server.
Developing a Remote Component or Custom App
To develop a remote component or custom app, use the Starter Kit as reference. Steps are given
below:
1. Access the Paciolan/remote-component-starter workspace:
mkdir my-component
cd my-component
git init
# pull the remote component starter kit
# install dependencies
npm ci
2. Develop the component. Refer to the Appendix A: Developing the Remote Component
section for details.
3. Launch the Web server and debug:
a. Change the host and server name as required in package.json: "webpack-dev-
b. npm run start
4. Build the component:
a. Run the following command:
npm run build
The build command will create the dist directory.
b. Copy and rename the dist/main.js file. For example, you may rename it to myApp.js or
any other suitable name.
c. Upload myApp.js using App Register(/register) page.
Linking the Remote Component with JedAI
1. Create and upload the app.
a. Register the app: Specify a display name and identifier for the new app and then upload
the app's .js file.
b. If the app identifier you specify exists already, you are warned to choose a different
identifier. If you continue with the same identifier, the code (js file)in the system is
updated with the new file.
c. Once the app has been registered, you should see a message like the one displayed
below.
2. Associate the app with the dataset. Once the app is registered, you need to associate a
dataset with the app.
3. Create a project.
4. The custom dynamic component will render as shown below.
Using the Customized Dashboard Template
As shown in the shaded box, you can build your own customized web application through the
Dashboard. You can start by building a Dashboard template using a small sample dataset, and
then apply this template on the real dataset. The calculate engine plays an important role in
converting the dataset into a dashboard-understandable format within the JedAI database.
Steps for building a customized web application through the Dashboard:
1. Create a dashboard as detailed in the Building the Dashboard in Superset section.
2. Download the dashboard template (json file).
3. Download the dashboard snapshot.
4. With the JedAI web app, register the dashboard with the template downloaded in the previous
step.
a. Provide a template name (Test in this example).
b. Choose the template json file.
c. Upload the file in the system.
d. Register to record the information.
In the Preview Graph section on the right side of the screen, you can optionally
upload a sample screenshot of the dashboard for demo purposes.
5. Create a new dashboard for a dataset.
a. Choose a registered dataset and click the Create Dashboard button.
b. Select a template from the list, which includes three sample dashboard templates and
the templates registered by the user.
c. Specify a dashboard name.
d. Click the Create button to create a new dashboard.
6. Register the calculate engine to the dashboard template. This is an important step. After you
enter the new dashboard, you will be asked to register the calculate engine.
The calculate engine will be registered to the dashboard template, not the dashboard.
For example, you register a dashboard template called cui_area, then create a
dashboard based on this template called cui_area_dashboard. The first time you enter
the cui_area_dashboard dashboard, you need to register the calculate engine to the
cui_area dashboard template. Then, if you create another dashboard based on the
cui_area template, you do not need to register the calculate engine again.
You can choose to register an existing Mozart calculate engine or your own calculate
engine. As shown below, three calculate engines (corresponding to three JedAI
examples in Superset) are available to you to choose.
However, if you have your own calculate engine, it is possible to register that instead.
See Defining Your Own Calculate Engine section for details.
The dashboard_id can be generated from the front end in the url path after you enter the
dashboard.
dashboard_id = 'a7113352-64da-4984-b2f5-cf331a1bfa7a'
ECA = EXAMPLE_CUI_AREA(dashboard_id)
ECA.calculate_engine_name
ECA.all_tables()
ECA.cal_data()
Defining Your Own Calculate Engine
Suppose the dashboard downloaded from Superset has multiple charts. Each chart is generated
from a dataset in the Superset.
As shown above, the dataset main.insts, which corresponds to the table name insts in the
EXAMPLE_CUI_AREA engine.
If you have multiple charts in the dashboard, multiple datasets will be needed and you must
define the tables and calc method in the class engine.
The calculate engine should be a python .py file and defined in the Class base on
MozartDashboardCalculation. See the example below:
Naming Method: Engine name (in frontend) = py File name = Class name =
calculate_engine_name defined in py
The Python class should contain two functions: all_tables and cal_data.
all_tables: This function is used to return all the tables used by the dashboard. In the
EXAMPLE_CUI_AREA engine, the returned tables should be ["insts", "hinsts",
"analysis_views"].
cal_data: This function is used to calculate the tables needed (self.save_df to store the
dataframe data). Every table returned in all_tables() should have self.save_df.
You can test the calculate engine by using the same dataset used in the Superset. Check
whether they have same results.
To view an example, refer to 05_dashboard_develop_example.ipynb in notebook/tutorials.
Sample calculate engine code (EXAMPLE_CUI_AREA.py)
# this should be in py File name " EXAMPLE_CUI_AREA.py"
import pandas as pd
from mozart_dashboard_cal_engine.base_cal_engine import MozartDashboardCalculation
class EXAMPLE_CUI_AREA(MozartDashboardCalculation):
"""calculate_engine_name is required."""
calculate_engine_name = "EXAMPLE_CUI_AREA"
def all_tables(self):
"""This function is required."""
"""Please return all tables need to be calculated!"""
return ["insts", "hinsts", "analysis_views"]
def cal_data(self):
"""This function is required."""
"""Please give calculate logic here!"""
# delete existing tables first
self.drop_existing_tables()
datasource = self.get_dashboard_db()[0]
path = datasource["path"]
tables_path = path.split("file://")[1]
# load insts
print("Loading: insts")
insts = pd.read_parquet("%s/%s" % (tables_path, "par.insts"))[
["inst","area","base_cell","name","parent","area","check_type",
"view_name",]]
self.save_df(
insts,
"insts",
if_exists="replace",
)
# load hinsts
print("Loading: hinsts")
hinsts = pd.read_parquet("%s/%s" % (tables_path, "par.hinsts"))[
["name", "area"]
]
self.save_df(
hinsts,
"hinsts",
if_exists="replace",
)
# load analysis_views
print("Loading: analysis_views")
analysis_views = pd.read_parquet(
"%s/%s" % (tables_path, "par.analysis_views")
)
self.save_df(
analysis_views,
"analysis_views",
if_exists="replace",
)
You can test the calculate engine you defined in Notebook before registering it. Refer to
05_dashboard_develop_example.ipynb.
Developing a Customized App
You can create your own custom backend app by following the steps below:
Initial Setup
Install JedAI as described in the Single-node Mode Installation section.
Start the App Server
After JedAI starts, star the app server:
1. Set up the environment for starting the app server:
source {JED_INSTALL_PATH}/setup.csh
setenv PYTHONPATH ../:$PYTHONPATH
2. Configure JEDAI_URL to point to the web server URL where JedAI is installed:
setenv JEDAI_URL http://{JEDAI_HOST}:{JEDAI_PORT}
3. Start the app server:
cd app_server
4. Access swagger ui to test the REST APIs:
url: http://{APP_SERVER_HOST}:{APP_SERVER_PORT}/api/analytics/ui
Develop the Rest API on the App Server
Suppose you want to develop a new app named hello:
1. Create two files:
jedai_app_server/apps/analytics_hello.py
jedai_app_server/openapi/apps/hello.yaml
2. Define the yaml file:
The name should be the same as the app name.
Operations defines all REST APIs for this app, should be an array, each item will be a
REST API.
3. Specify the default python file. Each operation defined in the yaml file should have one
corresponding post function in the python file.
name: "{operation_name}_post"
Wrapped by @operation
You can import JedAI python APIs to develop your own REST APIs. For more details,
see Appendix D: Data Analytics Python APIs.
4. Specify a mapping relationship.
Release
For integration inside JedAI, release the following files to JedAI:
jedai_app_server/apps/analytics_*.py
jedai_app_server/openapi/apps/*.yaml
Related python functions
Machine Learning Operation Service (MLOps)

---
## Machine Learning Operation Service

(MLOps)

---