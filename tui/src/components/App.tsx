import { useAppState } from "../hooks/useAppState";
import { Header } from "../components/Header";
import { Sidebar } from "../components/Sidebar";
import { Dashboard } from "../screens/Dashboard";
import { Deployments } from "../screens/Deployments";
import { Accounts } from "../screens/Accounts";
import { Analytics } from "../screens/Analytics";
import { Settings } from "../screens/Settings";
import { Sync } from "../screens/Sync";

export function App() {
  const {
    state,
    setScreen,
    handleSync,
    handleDeploy,
    handleRemove,
    handleNukeAll,
    handleAddAccount,
    handleRemoveAccount,
    handleSwitchAccount,
    handleSaveSettings,
  } = useAppState();

  const renderScreen = () => {
    switch (state.screen) {
      case "dashboard":
        return <Dashboard state={state} />;
      case "deployments":
        return (
          <Deployments
            state={state}
            onDeploy={handleDeploy}
            onRemove={handleRemove}
            onNukeAll={handleNukeAll}
          />
        );
      case "accounts":
        return (
          <Accounts
            state={state}
            onAddAccount={handleAddAccount}
            onRemoveAccount={handleRemoveAccount}
            onSwitchAccount={handleSwitchAccount}
          />
        );
      case "analytics":
        return <Analytics state={state} />;
      case "settings":
        return <Settings state={state} onSave={handleSaveSettings} />;
      case "sync":
        return <Sync state={state} onSync={handleSync} />;
      default:
        return <Dashboard state={state} />;
    }
  };

  return (
    <box flexDirection="column" style={{ width: "100%", height: "100%" }}>
      <Header
        activeScreen={state.screen}
        syncing={state.syncing}
        accountCount={Object.keys(state.accounts).length}
        deployCount={Object.keys(state.deployments).length}
      />
      <box flexDirection="row" style={{ flexGrow: 1 }}>
        <Sidebar activeScreen={state.screen} onNavigate={setScreen} />
        <box style={{ flexGrow: 1, padding: 0 }}>{renderScreen()}</box>
      </box>
    </box>
  );
}
