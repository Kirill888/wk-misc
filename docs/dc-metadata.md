## Current State of Spatial Metadata

This is a sample from current public docs

```yaml
extent:
  coord:
    ll: {lat: -44.000138890272005, lon: 112.99986111}
    lr: {lat: -44.000138890272005, lon: 153.99986111032797}
    ul: {lat: -10.00013889, lon: 112.99986111}
    ur: {lat: -10.00013889, lon: 153.99986111032797}
  from_dt: '2000-02-11T17:43:00'
  center_dt: '2000-02-21T11:54:00'
  to_dt: '2000-02-22T23:23:00'
grid_spatial:
  projection:
    geo_ref_points:
      ll: {x: 112.99986111, y: -44.000138890272005}
      lr: {x: 153.999861110328, y: -44.000138890272005}
      ul: {x: 112.99986111, y: -10.00013889}
      ur: {x: 153.999861110328, y: -10.00013889}
    spatial_reference: GEOGCS["GCS_WGS_1984",DATUM["WGS_1984",SPHEROID["WGS_84",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]
```

Explanation as to what exactly should go into those fields is a bit sparse:

>- *extent*
>   - Spatio-tempral (sic) extents of the data. Used for search in the database.
>- *geo_ref_points*
>   - Spatial extents of the data in the CRS of the data.
>- *valid_data* (optional)
>   - GeoJSON Geometry Object for the ‘data-full’ (non no-data) region of the data. Coordinates are assumed to be in the CRS of the data. Used to avoid loading useless parts of the dataset into memory. Only needs to be roughly correct. Prefer simpler geometry over accuracy.
>- *spatial_reference*
>   - Coordinate reference system the data is stored in. `EPSG:<code>` or WKT string.

### Problems

There are few issues

- No explanation for `center_dt`
   - Why is it needed?
   - Can it be omitted?
   - Where do I get it from?

- Why `_dt`? This usually means *delta*, as in difference, from what?

- Why `spatial_reference` and not `crs`/`srs` or `spatial_reference_system` if you want to be verbose

- Loose definition for `data-full`/`valid`/`non no-data` region
   - Is pixel considered valid if pixels in **ALL**  bands are valid or if **SOME** are?
   - Is it a region that contains no invalid data (**WRONG**)
   - Is it a region outside of which there is no valid data (**CORRECT**, I think)

- Strange format for `extent.coord` and `grid_spatial.projection.geo_ref_points`
   - Is it a bounding box?
   - Are these coordinates of the four corners of a raster?
   - Should it be axis-aligned, if yes why 4 points and not 2?
   - Why is it duplicated (`x,y` and `lon,lat`)?

The last one is the more serious one as it leads to incorrect spatial querying as described previously

- [Report](https://s3-ap-southeast-2.amazonaws.com/ga-aws-dea-dev-users/u60936/Datacube-Spatial-Query-Problem.html) about incorrect metadata in ARD products
- [Github Issue](https://github.com/opendatacube/datacube-core/issues/537) for code in `datacube-core` that performs incorrect computation for `extent`
- All of our prepare scripts (and also ingestor and stats) generate incorrect `extent` information

My interpretation so far is that `grid_spatial.projection.geo_ref_points` is meant to contain coordinates of the fours corners of the raster covered by the dataset in the native projection, hence the names `ll,lr,ul,ur`, lower/upper and left/right corner (corner is implied).

- What is a corner?
  - Center of a corner pixel (**WRONG**, but easy to use that by accident)
  - Actual corner of an image plane, the very edge of pixel data (**CORRECT**)
- What if dataset consists of many images covering slightly different spatial regions?
  - How do I compute lower left corner from 7 different lower left corners?
  - Should I supply Union or Intersection of all rasters?
  - Can I just pick one image as a reference?

Since `extent.coord` has exactly the same structure as `geo_ref_points`, except for using `lon/lat` in place of `x/y`, it strongly suggests to the user that these are just the four corners from `geo_ref_points` but in Lon/Lat this time. Given that all our own implementations do just that, it's not just a "maybe a problem", but a fact. See report linked above for the explanation of why this interpretation leads to incorrect spatial index being built by datacube. And we haven't mentioned discontinuity for polar regions/dateline, so let's mention that now, and never talk about it again.


## Suggested Changes to Metadata

### Main principles

- No duplication of spatial information, only supply extents in the native projection
- Drop `geo_ref_points`, supply axis aligned bounding box instead (4 values only)
- Drop `center_dt`, supply time range instead (2 values, possibly equal to each other, accept single value as a shorthand)
- Allow optional `valid` region, but be precise in the documentation on how it should be computed, back it up with sample implementation

Supplying bounding box instead of 4 corners makes it more obvious on how to combine spatial information about multiple bands. Supplying bounding box in the native projection only, removes the possibility of getting conversion to `lon/lat` wrong by end-user/auxiliary tool.

### Current design constraints

There are a number of assumptions in the implementation of ODC that make it impossible to implement above without significant refactoring.

Number one reason is that we pretend that we don't really have a spatial index in the first place. Instead what we have are user-configurable search fields that can be extracted from the dataset metadata document (this is configurable per product, via `metadata_type`). If product's `metadata_type` contains search fields named `time`,`lon`,`lat`, then, effectively, you have spatio-temporal index for datasets in that product.

Search parameters `time`, `lon`, `lat` are expected to be ranges, defining a 3d cube, that fully encloses data within the dataset. These are processed by the database server, so have to be computable from the metadata document stored in the database using generated SQL statements. Computation is limited to:

- Lookup list of values from JSON document
- Type conversion (`string` to `datetime` for example)
- Reduce list of values to a single value using one of:
  - First non empty value
  - Maximum value
  - Minimum value
- Construct range object from two values

At the lowest DB layer those spatio-temporal fields are no different to any other user defined search fields, except that combined indexes for `product_time_lat_lon` and `product_lat_lon_time` are built to speed up spatial queries. There is no way to request combined indexes to be built for an arbitrary set of search fields.

At the API level spatial index is a first class citizen, various methods, like querying area of interest via polygon in arbitrary projection, are supported. These queries are then converted to database extent queries using `lon/lat` fields and the results are then further refined using information stored under `grid_spatial`.

If we want to avoid duplicating spatial extent in the user supplied metadata document then we have to compute that at index time from the native extent information. We can then either inject it into the metadata document that is stored in the DB (no changes to DB schema needed), or refactor DB layer to accept spatio-temporal extents as a special, albeit optional, parameter (like current `added_by` property for example).

Injecting computed `lon/lat` extents into metadata may seem like an easier option, but it breaks another design assumption:

- Metadata stored in the DB is a verbatim translation from YAML (on disk) to JSON
  - **NOTE**: round tripping data is still not possible though, since not all values that can be represented by YAML can be represented by JSON, floating point `NaN` is one such value, but also larger integer values do not survive conversion to float, the only numeric type JSON supports.

So, injecting computed data into metadata document stored in DB would break dataset metadata integrity checks (DB vs filesystem) during (re-)indexing and would require hacky workarounds.


### Proposed Structure

I'm purposefully omitting exact structure proposal for now. This requires choosing names and exact representations and picking which fields to group together. I think this is best done as a group. To give you a taste for how large the design space is, below are some options for representing just the spatial bounding box alone

```yaml
bbox: [xmin, xmax, ymin, ymax]
--
bbox: [left, right, bottom, top]  # note different then above when y-axis has negative as top
--
bbox:
  xmin: <val>
  xmax: <val>
  ymin: <val>
  ymax: <val>
--
bbox:
   x: [min, max]
   y: [min, max]
--
bbox:
   x:
     min: <val>
     max: <val>
   y:
     min: <val>
     max: <val>
```

But then your data might be in `lon/lat`, so `x,y` is not always a good name, and if you don't use names but order like in `[xmin, xmax, ymin, ymax]` do you put `lon` first or `lat`?
