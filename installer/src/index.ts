export { Installer } from "./core/installer";
export { detectPlatform, getPrimaryPackageManager } from "./core/platform";
export { PackageInstaller } from "./core/package-manager";
export { EnvironmentManager } from "./core/environment";
export { Downloader } from "./core/downloader";
export { ConfigManager } from "./core/config";
export { Logger } from "./core/logger";
export { RollbackManager } from "./core/rollback";
export { Verifier } from "./core/verification";
export { UpdateChecker } from "./core/update";
export {
  PACKAGE_REGISTRY,
  getPackageByName,
  getPackagesByCategory,
  getRequiredPackages,
  searchPackages,
} from "./packages/definitions";
export type * from "./core/types";
