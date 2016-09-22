import getpass

from .sign import Sign
from . import util
from . import pulp
from . import satellite

try:
    from . import Atomic
except ImportError:
    from atomic import Atomic # pylint: disable=relative-import

ATOMIC_CONFIG = util.get_atomic_config()

def cli(subparser):
    signer = ATOMIC_CONFIG.get('default_signer', None)
    # atomic push
    pushp = subparser.add_parser(
        "push", aliases=['upload'], help=_("push latest image to repository"),
        epilog="push the latest specified image to a repository.")
    pushp.set_defaults(_class=Push, func='push')
    # making it so we cannot call both the --pulp and --satellite commands
    # at the same time (mutually exclusive)
    pushgroup = pushp.add_mutually_exclusive_group()
    pushgroup.add_argument("--pulp",
                           default=False,
                           action="store_true",
                           help=_("push image using pulp"))
    pushgroup.add_argument("--satellite",
                           default=False,
                           action="store_true",
                           help=_("push image using Satellite"))

    pushp.add_argument("--verify_ssl",
                         default=None,
                         action="store_true",
                         help=_("flag to verify ssl of registry"))
    pushp.add_argument("-U", "--url",
                         dest="url",
                         default=None,
                         help=_("URL for remote registry"))
    pushp.add_argument("-u", "--username",
                         default=None,
                         dest="username",
                         help=_("Username for remote registry"))
    pushp.add_argument("-p", "--password",
                         default=None,
                         dest="password",
                         help=_("Password for remote registry"))
    pushp.add_argument("image", help=_("container image"))
    pushp.add_argument("-a", "--activation_key",
                         default=None,
                         dest="activation_key",
                         help=_("Activation Key"))
    pushp.add_argument("-r", "--repository_id",
                         default=None,
                         dest="repo_id",
                         help=_("Repository ID"))
    pushp.add_argument("-t", "--type", dest="reg_type", default=None,
                       help=_("Push to an alternative registry type."))
    pushp.add_argument("--sign-by", dest="sign_by", default=signer,
                       help=_("Name of the signing key. Currently %s, "
                              "default can be defined in /etc/atomic.conf" % signer))
    # pushp.add_argument("--activation_key_name",
    #                      default=None,
    #                      dest="activation_key_name",
    #                      help=_("Activation Key Name"))
    # pushp.add_argument("--repo_name", "--repository_name",
    #                      default=None,
    #                      dest="repo_name",
    #                      help=_("Repository Name"))
    # pushp.add_argument("--org_name", "--organization_name",
    #                      default=None,
    #                      dest="org_name",
    #                      help=_("Organization Name"))

class Push(Atomic):
    def push(self):
        self.ping()
        if self.args.debug:
            util.write_out(str(self.args))

        # This allows a user to turn off signing when a global
        # sign_by has been defined in /etc/atomic.conf and saves
        # us from having to define something like --no-sign
        if self.args.sign_by == "None":
            self.args.sign_by = None

        # Priority order:
        # If user passes in a password/username/url/ssl flag, use that
        # If not, read from the config file
        # If still nothing, ask again for registry user/pass
        if self.args.pulp:
            config = pulp.PulpConfig().config()

        if self.args.satellite:
            config = satellite.SatelliteConfig().config()

        if (self.args.satellite | self.args.pulp):
            if not self.args.username:
                self.args.username = config["username"]
            if not self.args.password:
                self.args.password = config["password"]
            if not self.args.url:
                self.args.url = config["url"]
            if self.args.verify_ssl is None:
                self.args.verify_ssl = config["verify_ssl"]

        if self.args.verify_ssl is None:
            self.args.verify_ssl = False

        if not self.args.username:
            self.args.username = util.input("Registry Username: ")

        if not self.args.password:
            self.args.password = getpass.getpass("Registry Password: ")

        if (self.args.satellite | self.args.pulp):
            if not self.args.url:
                self.args.url = util.input("URL: ")

        if self.args.pulp:
            return pulp.push_image_to_pulp(self.image, self.args.url,
                                           self.args.username,
                                           self.args.password,
                                           self.args.verify_ssl,
                                           self.d)

        if self.args.satellite:
            if not self.args.activation_key:
                self.args.activation_key = util.input("Activation Key: ")
            if not self.args.repo_id:
                self.args.repo_id = util.input("Repository ID: ")
            return satellite.push_image_to_satellite(self.image,
                                                     self.args.url,
                                                     self.args.username,
                                                     self.args.password,
                                                     self.args.verify_ssl,
                                                     self.d,
                                                     self.args.activation_key,
                                                     self.args.repo_id,
                                                     self.args.debug)

        else:
            reg, _, tag = util.decompose(self.image)
            if not tag:
                raise ValueError("The image being pushed must have a tag")

            if self.args.password and self.args.username:
                self.d.login(username=self.args.username, password=self.args.password, registry=reg)

            sign_local = True
            local_image = "docker-daemon:{}".format(self.image)
            if self.args.reg_type == "atomic":
                remote_image = "atomic:{}".format(self.image)
                sign_local = False
            else:
                remote_image = "docker://{}".format(self.image)

            sign = True if self.args.sign_by else False
            if sign and self.args.debug:
                util.write_out("\nSigning with '{}'\n".format(self.args.sign_by))

            insecure = True if util.is_insecure_registry(self.d.info()['RegistryConfig'], util.strip_port(reg)) else False

            # We must push the file to the registry first prior to performing a
            # local signature because the manifest file must be on the registry
            return_code = util.skopeo_copy(local_image, remote_image, debug=self.args.debug,
                                           sign_by=self.args.sign_by if not sign_local else None, insecure=insecure)

            if return_code != 0:
                raise ValueError("Pushing {} failed.".format(self.image))
            if self.args.debug:
                util.write_out("Pushed: {}".format(self.image))

            if sign_local and sign:
                if self.args.debug:
                    util.write_out("Need to create a local signature")
                atomic_sign = Sign()
                atomic_sign.set_args(self.args)
                atomic_sign.sign(in_signature_path=None, images=[self.image])

