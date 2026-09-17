package ru.elytrix.bots;

import org.bukkit.configuration.file.FileConfiguration;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;

import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.function.IntSupplier;

final class ProxySyncSender {
    private final JavaPlugin plugin;
    private final IntSupplier count;
    private final String host, secret;
    private final int port;
    private BukkitTask task;

    ProxySyncSender(JavaPlugin plugin, IntSupplier count) {
        this.plugin=plugin; this.count=count;
        FileConfiguration c=plugin.getConfig();
        host=c.getString("proxy-sync.host","127.0.0.1");
        port=c.getInt("proxy-sync.port",29175);
        secret=c.getString("proxy-sync.secret","change-me");
    }
    void start() {
        if(!plugin.getConfig().getBoolean("proxy-sync.enabled",true)) return;
        long ticks=Math.max(20,plugin.getConfig().getLong("proxy-sync.interval-seconds",3)*20);
        task=plugin.getServer().getScheduler().runTaskTimerAsynchronously(plugin,()->send(count.getAsInt()),1,ticks);
    }
    void stop() { if(task!=null)task.cancel(); send(0); }
    void send(int bots) {
        String payload=secret+":"+Math.max(0,bots)+":"+System.currentTimeMillis();
        byte[] bytes=payload.getBytes(StandardCharsets.UTF_8);
        try(DatagramSocket socket=new DatagramSocket()) {
            socket.send(new DatagramPacket(bytes,bytes.length,InetAddress.getByName(host),port));
        } catch(Exception ex) { plugin.getLogger().warning("Proxy sync failed: "+ex.getMessage()); }
    }
}
