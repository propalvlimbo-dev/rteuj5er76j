package ru.elytrix.bots.bungee;

import net.md_5.bungee.api.ProxyServer;
import net.md_5.bungee.api.ServerPing;
import net.md_5.bungee.api.config.ServerInfo;
import net.md_5.bungee.api.event.ProxyPingEvent;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.api.plugin.Plugin;
import net.md_5.bungee.config.Configuration;
import net.md_5.bungee.config.ConfigurationProvider;
import net.md_5.bungee.config.YamlConfiguration;
import net.md_5.bungee.event.EventHandler;
import net.md_5.bungee.event.EventPriority;

import java.io.*;
import java.nio.file.Files;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public final class ElytrixBotsBungee extends Plugin implements Listener {
    private final AtomicInteger fakeOnline = new AtomicInteger();
    private Set<String> configuredServers = Collections.emptySet();

    @Override public void onEnable() {
        try { loadConfig(); } catch (IOException ex) { throw new RuntimeException("Cannot load config", ex); }
        ProxyServer.getInstance().getPluginManager().registerListener(this, this);
        Configuration config = readConfig();
        fakeOnline.set(Math.max(0, config.getInt("fake-players", 5)));
        int seconds = Math.max(3, config.getInt("refresh-seconds", 10));
        ProxyServer.getInstance().getScheduler().schedule(this, this::refresh, 1, seconds, TimeUnit.SECONDS);
        getLogger().info("Enabled. Backend ping synchronization does not create bot connections.");
    }

    @EventHandler(priority = 127) public void onPing(ProxyPingEvent event) {
        ServerPing response = event.getResponse();
        if (response == null) return;
        ServerPing.Players players = response.getPlayers();
        int total = ProxyServer.getInstance().getOnlineCount() + fakeOnline.get();
        if (players == null) players = new ServerPing.Players(total + 1, total, null);
        else {
            players.setOnline(total);
            players.setMax(Math.max(players.getMax(), total + 1));
        }
        response.setPlayers(players);
        event.setResponse(response);
    }

    private void refresh() {
        Collection<ServerInfo> servers = ProxyServer.getInstance().getServers().values();
        List<ServerInfo> selected = new ArrayList<>();
        for (ServerInfo server : servers) if (configuredServers.isEmpty() || configuredServers.contains(server.getName())) selected.add(server);
        if (selected.isEmpty()) return;
        AtomicInteger pending = new AtomicInteger(selected.size());
        AtomicInteger sum = new AtomicInteger();
        for (ServerInfo server : selected) server.ping((result, error) -> {
            if (error == null && result != null && result.getPlayers() != null) {
                // Backend PlayerList содержит ботов; proxy ServerInfo содержит только реальные соединения.
                sum.addAndGet(Math.max(0, result.getPlayers().getOnline() - server.getPlayers().size()));
            }
            if (pending.decrementAndGet() == 0 && sum.get() > 0) fakeOnline.set(sum.get());
        });
    }

    private void loadConfig() throws IOException {
        if (!getDataFolder().exists()) getDataFolder().mkdirs();
        File file = new File(getDataFolder(), "config.yml");
        if (!file.exists()) try (InputStream in=getResourceAsStream("config.yml")) { Files.copy(in, file.toPath()); }
        Configuration c=readConfig(); configuredServers=new HashSet<>(c.getStringList("servers"));
    }
    private Configuration readConfig() {
        try { return ConfigurationProvider.getProvider(YamlConfiguration.class).load(new File(getDataFolder(), "config.yml")); }
        catch (IOException ex) { throw new RuntimeException(ex); }
    }
}
