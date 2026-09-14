package ru.elytrix.efc.exempt;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.bukkit.Bukkit;
import org.bukkit.GameMode;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerChangedWorldEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerRespawnEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;

/**
 * Exemptions — сердце защиты честных игроков.
 * Любое сомнение трактуем в пользу игрока: лучше пропустить чит, чем кикнуть легита.
 * TODO билд №2: пинг и версия клиента через PacketEvents/ViaVersion.
 */
public final class ExemptionManager implements Listener {

    private final ElytrixFuckCheats plugin;
    private final Map<UUID, Long> lastTeleport = new ConcurrentHashMap<>();
    private final Map<UUID, Long> timedBypass = new ConcurrentHashMap<>();

    public ExemptionManager(ElytrixFuckCheats plugin) {
        this.plugin = plugin;
    }

    public boolean isExempt(Player player, Category category) {
        if (player == null || !player.isOnline() || player.isDead()) {
            return true;
        }
        // Ручной байпас: пермишен или /efc exempt.
        if (player.hasPermission("efc.bypass")) {
            return true;
        }
        Long until = timedBypass.get(player.getUniqueId());
        if (until != null && System.currentTimeMillis() < until) {
            return true;
        }
        // Креатив/спектатор не проверяем.
        if (plugin.getConfigManager().creativeBypass()) {
            GameMode mode = player.getGameMode();
            if (mode == GameMode.CREATIVE || mode == GameMode.SPECTATOR) {
                return true;
            }
        }
        long now = System.currentTimeMillis();
        // Грейс после входа.
        if (now - plugin.getDataManager().get(player).getJoinTime()
                < plugin.getConfigManager().joinGraceMs()) {
            return true;
        }
        // Грейс после телепорта (движение и бой врут после TP).
        Long teleport = lastTeleport.get(player.getUniqueId());
        if (teleport != null && now - teleport < plugin.getConfigManager().teleportGraceMs()) {
            return true;
        }
        // Лаги сервера — не вина игрока.
        if (getTps() < plugin.getConfigManager().minTps()) {
            return true;
        }
        return false;
    }

    /** Временный байпас через /efc exempt. */
    public void addTimedBypass(UUID uuid, long seconds) {
        timedBypass.put(uuid, System.currentTimeMillis() + seconds * 1000);
    }

    private double getTps() {
        try {
            return Bukkit.getTPS()[0];
        } catch (Throwable ignored) {
            return 20.0;
        }
    }

    @EventHandler
    public void onTeleport(PlayerTeleportEvent event) {
        lastTeleport.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onRespawn(PlayerRespawnEvent event) {
        lastTeleport.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onWorldChange(PlayerChangedWorldEvent event) {
        lastTeleport.put(event.getPlayer().getUniqueId(), System.currentTimeMillis());
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        lastTeleport.remove(event.getPlayer().getUniqueId());
        timedBypass.remove(event.getPlayer().getUniqueId());
    }
}
