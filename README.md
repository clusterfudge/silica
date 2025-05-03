# silica 

silica is a command line tool for create workspaces for agents on top of piku

silica stores its configuration in ~/.config/silica
it's configurable values can be set using `silica config:set key=value` or by running `silica setup` for an interactive mode (which uses rich for prettiness)
`silica config` shows all current configuration


silica writes environment information to a config file in the .silica/ directory of the repository in which it is invoked. if its invoked anywhere within the tree of a git checkout, it puts the .silica/ directory in the root.

by default, the piku cli will connect to the remote named `piku`
it also accepts a `-r` parameter to specify a different remote. We'll create a new remote (named agent by default, but with the option for an alternative name at creation time) 

silica roughly works by creating an empty piku application on the remote with a `code` directory, then syncing the local git repository into it in a directory named `code`. It has a Procfile that for now will just run `web: hdev view-memory --port $PORT`, a pyproject.toml file that installs the latest heare-developer version. sound good?

roughly, create should create an empty git repo, copy a silica-env pyproject.toml into it, commit, and then create a 
piku remote. push _that_ repository. Also include the procfile we discussed above. 
the git repo can be in the local .silica directory.
the pyproject.toml should be stored as a string in the silica tool.





`create` creates a new environment as a remote, sets up credentials and agent
 - credentials include github (via gh auth token) and an anthropic api key (found from envvar or .env file)






`status` fetch and visualize conversations
figure out the session that is currently (or most recently) active, based on the output of `hdev sessions` 

`todos` means for scheduling work on an agent instance
TBD

`destroy` destroys a remote environment
standard piku destroy, using the correct `-r` flag to specify the agent remote
