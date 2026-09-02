"""Road-network graph helpers for the drive-time measurement.

TIGER lacks one-way/turn data, so the graph is undirected — standard for
screening-level accessibility. Endpoints are snapped to a 1 m grid so
segments that share an intersection connect despite float noise.
"""
import networkx as nx

MPH_TO_M_PER_MIN = 26.8224

# mph by TIGER MTFCC; editable. Unlisted classes get DEFAULT_MPH.
SPEEDS = {"S1100": 65, "S1200": 45, "S1400": 30, "S1500": 15,
          "S1630": 35, "S1640": 30}
DEFAULT_MPH = 25

SURFACE = {"S1200", "S1400", "S1500", "S1640"}  # roads you can be ON before a ramp


def _snap(coord):
    return (round(coord[0]), round(coord[1]))  # 1 m grid, metric CRS required


def build_graph(roads_m):
    """roads_m: GeoDataFrame of LineStrings in a metric CRS with MTFCC.

    Returns (graph, node_list). Edge weight = minutes at the class speed.
    Each LineString contributes one edge between its snapped endpoints,
    weighted by full geometric length (interior curvature counted).
    """
    g = nx.Graph()
    for mtfcc, geom in zip(roads_m["MTFCC"], roads_m.geometry):
        if geom is None or geom.is_empty:
            continue
        mph = SPEEDS.get(mtfcc, DEFAULT_MPH)
        coords = list(geom.coords)
        a, b = _snap(coords[0]), _snap(coords[-1])
        if a == b:
            continue  # degenerate loop after snapping
        minutes = geom.length / (mph * MPH_TO_M_PER_MIN)
        # keep the fastest edge if duplicate connections exist
        if not g.has_edge(a, b) or g[a][b]["minutes"] > minutes:
            g.add_edge(a, b, minutes=minutes)
    print(f"network: graph with {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    return g, list(g.nodes)


def find_access_points(roads_m, strict=False):
    """Ramp (S1630) endpoints that touch a surface road — the bottom of the
    on-ramp, i.e. where the ordinary network reaches the highway system."""
    surface_ends = set()
    for mtfcc, geom in zip(roads_m["MTFCC"], roads_m.geometry):
        if mtfcc in SURFACE and geom is not None and not geom.is_empty:
            coords = list(geom.coords)
            surface_ends.add(_snap(coords[0]))
            surface_ends.add(_snap(coords[-1]))
    access = set()
    for mtfcc, geom in zip(roads_m["MTFCC"], roads_m.geometry):
        if mtfcc == "S1630" and geom is not None and not geom.is_empty:
            coords = list(geom.coords)
            for end in (_snap(coords[0]), _snap(coords[-1])):
                if end in surface_ends:
                    access.add(end)
    if not access and strict:
        raise RuntimeError("network: no highway access points found (no S1630 ramp "
                           "endpoint touches a surface road) — this county may have "
                           "no interchange, or the road extract is wrong")
    print(f"network: {len(access)} highway access points")
    return sorted(access)


def node_minutes(g, access_nodes):
    """Multi-source Dijkstra: minutes from every reachable node to the
    nearest access node. Unreachable nodes are absent from the result."""
    sources = [n for n in access_nodes if g.has_node(n)]
    if not sources:
        raise RuntimeError("network: no access node exists in the graph")
    return nx.multi_source_dijkstra_path_length(g, sources, weight="minutes")
