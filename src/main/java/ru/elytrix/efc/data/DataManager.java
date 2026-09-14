package ru.elytrix.efc.data;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import ru.elytrix.efc.ElytrixFuckCheats;

/** Хранилище PlayerData + ежесекундное затухание VL. */
public final class DataManager implements Listener {

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, PlayerData> data = new ConcurrentHashMap<>();

    public DataManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
        plugin.getServer().getScheduler().runTaskTimerAsynchronously(plugin, this::decayAll, 20L, 20L);
    }

    public PlayerData get(Player player) {
        return data.computeIfAbsent(player.getUniqueId(), uuid -> new PlayerData(plugin, uuid));
    }

    public PlayerData get(UUID uuid) {
        return data.get(uuid);
    }

    private void decayAll() {
        double amount = plugin.getConfigManager().vlDecayPerSecond();
        for (PlayerData playerData : data.values()) {
            playerData.decay(amount);
        }
    }

    public void clear() {
        data.clear();
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        get(event.getPlayer());
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        data.remove(event.getPlayer().getUniqueId());
    }
}
