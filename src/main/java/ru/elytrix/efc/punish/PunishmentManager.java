package ru.elytrix.efc.punish;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Check;
import ru.elytrix.efc.data.PlayerData;

/**
 * Наказания. Только когда VL превысил max-vl проверки.
 * По умолчанию: консольные команды (кик). Автобана нет.
 * Возвращает, было ли наказание (false — кулдаун или порог).
 */
public final class PunishmentManager {

    private final ElytrixFuckCheats plugin;
    private final Map<String, Long> lastPunish = new ConcurrentHashMap<>();

    public PunishmentManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    public boolean onFlag(PlayerData data, Check check, double vl) {
        if (vl < check.getMaxVl()) {
            return false;
        }
        Player player = data.getPlayer();
        if (player == null) {
            return false;
        }
        String key = player.getUniqueId() + ":" + check.id();
        long now = System.currentTimeMillis();
        Long last = lastPunish.get(key);
        if (last != null && now - last < plugin.getConfigManager().punishCooldownMs()) {
            return false;
        }
        lastPunish.put(key, now);

        List<String> commands = plugin.getConfigManager().punishCommands(check.configKey());
        UUID uuid = player.getUniqueId();
        String name = player.getName();
        plugin.getServer().getScheduler().runTask(plugin, () -> {
            Player target = plugin.getServer().getPlayer(uuid);
            if (target == null || !target.isOnline()) {
                return;
            }
            for (String raw : commands) {
                String command = raw
                        .replace("%player%", name)
                        .replace("%check%", check.id())
                        .replace("%vl%", String.valueOf(Math.round(vl)));
                plugin.getServer().dispatchCommand(plugin.getServer().getConsoleSender(), command);
            }
        });
        return true;
    }
}
