package ru.elytrix.efc.alert;

import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.ChatColor;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.data.PlayerData;

/** Алерты стаффу в чат + verbose-дебаг для настройки. */
public final class AlertManager implements Listener {

    private final ElytrixFuckCheats plugin;
    private final Set<UUID> alertsOn = ConcurrentHashMap.newKeySet();
    private final Set<UUID> verboseOn = ConcurrentHashMap.newKeySet();

    public AlertManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    public void alert(PlayerData data, Check check, String details, double vl) {
        Player cheater = data.getPlayer();
        String suspect = cheater == null ? "?" : cheater.getName();
        String message = plugin.getConfigManager().alertFormat()
                .replace("%prefix%", plugin.getConfigManager().prefix())
                .replace("%player%", suspect)
                .replace("%check%", check.id())
                .replace("%vl%", String.valueOf(Math.round(vl)))
                .replace("%details%", details);
        message = ChatColor.translateAlternateColorCodes('&', message);

        if (plugin.getConfigManager().consoleAlerts()) {
            plugin.getLogger().info(ChatColor.stripColor(message));
        }
        for (Player staff : plugin.getServer().getOnlinePlayers()) {
            if (alertsOn.contains(staff.getUniqueId())) {
                staff.sendMessage(message);
            }
        }
    }

    /** Дебаг-строка для /efc verbose. */
    public void debug(String message) {
        String out = ChatColor.translateAlternateColorCodes('&',
                plugin.getConfigManager().prefix() + " &7[debug] " + message);
        for (Player staff : plugin.getServer().getOnlinePlayers()) {
            if (verboseOn.contains(staff.getUniqueId())) {
                staff.sendMessage(out);
            }
        }
    }

    public boolean toggleAlerts(Player staff) {
        UUID uuid = staff.getUniqueId();
        if (alertsOn.contains(uuid)) {
            alertsOn.remove(uuid);
            return false;
        }
        alertsOn.add(uuid);
        return true;
    }

    public boolean toggleVerbose(Player staff) {
        UUID uuid = staff.getUniqueId();
        if (verboseOn.contains(uuid)) {
            verboseOn.remove(uuid);
            return false;
        }
        verboseOn.add(uuid);
        return true;
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        Player player = event.getPlayer();
        // Алерты включены по умолчанию у всех с правом.
        if (player.hasPermission("efc.alerts")) {
            alertsOn.add(player.getUniqueId());
        } else {
            alertsOn.remove(player.getUniqueId());
        }
        verboseOn.remove(player.getUniqueId());
    }
}
